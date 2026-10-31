"""`vasty serve`.

Without `--on`, `serve` resolves settings the same way `reserve` does and
reserves a box with `run_ttl` (or `--ttl`). With `--on` it serves on that box.
`--model` is any name or box path `vllm serve` accepts.

Tokens after `--` are appended to the `vllm serve` argv. `serve` owns the
endpoint and the key, so `--host`, `--port` and `--api-key` among them raise
`invalid_arguments` before any provider call.

The box's image supplies vLLM. On the box, `serve` checks for `vllm` on PATH
and raises `vllm_missing` when it is absent. It then starts `vllm serve` as a
`serve` job on port 8000 with a fresh `vasty-` key, and polls `/v1/models`
with that key until it answers 200. The job script exports the key as
`VLLM_API_KEY`, so the `vllm serve` command line carries no secret. With
`--bind-local` vLLM listens on 127.0.0.1 and the poll runs on the box with
curl. `serve_failed` carries the job's last log lines with the key redacted.
Any failure after the reserve releases a box this call created.
"""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from typing import Any

from vasty import engine
from vasty.cli import Outcome
from vasty.commands._common import (
    finish_job,
    lease_warnings,
    merge_swept,
    merge_warnings,
    next_job_id,
    pick_lease,
    put_job,
    require_tools,
    save_lease,
)
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.models import SERVE_PORT, CachedLease, Job, ServeResult, WarningItem
from vasty.remote import LOG_LINES, SshTarget
from vasty.state import effective_expiry
from vasty.timeutil import iso

READY_DEADLINE_S = 1800.0
POLL_INTERVAL_S = 5.0
HTTP_TIMEOUT_S = 5.0
PREFLIGHT_TIMEOUT_S = 30.0
PREFLIGHT_COMMAND = "command -v vllm"
VLLM_IMAGE = "vllm/vllm-openai:v0.32.0"
LOG_TAIL_BYTES = 64 * 1024
# vLLM flags that `serve` sets itself.
OWNED_FLAGS = ("--host", "--port", "--api-key")


def check_extra(extra: list[str]) -> None:
    """Raise `invalid_arguments` when `extra` sets a flag in `OWNED_FLAGS`."""
    for token in extra:
        flag = token.split("=", 1)[0].replace("_", "-")
        if flag in OWNED_FLAGS:
            raise invalid(
                f"serve sets {flag} itself.",
                "Drop --host, --port and --api-key after --.",
            )


def server_argv(model: str, host: str, extra: list[str]) -> list[str]:
    """Return the `vllm serve` argv; the key goes in `VLLM_API_KEY`."""
    return ["vllm", "serve", model, "--host", host, "--port", str(SERVE_PORT), *extra]


def redact_tail(lines: list[str], key: str) -> list[str]:
    """Replace `key` with `<redacted>` and keep the last `LOG_TAIL_BYTES` bytes of the lines."""
    text = "\n".join(line.replace(key, "<redacted>") for line in lines)
    return text.encode("utf-8")[-LOG_TAIL_BYTES:].decode("utf-8", errors="ignore").splitlines()


def probe_command(key: str) -> str:
    """Return the curl command that prints the HTTP status of the box-local `/v1/models`."""
    url = f"http://127.0.0.1:{SERVE_PORT}/v1/models"
    return (
        f"curl -s -o /dev/null -m {int(HTTP_TIMEOUT_S)} -w '%{{http_code}}' "
        f"-H {shlex.quote('Authorization: Bearer ' + key)} {url}"
    )


@dataclass
class _Plan:
    model: str
    extra: list[str]
    bind_local: bool


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    auto = args.on is None
    extra = list(args.command or [])
    check_extra(extra)
    plan = _Plan(args.model, extra, bool(args.bind_local))
    require_tools(ctx, "ssh")

    snap = engine.refresh(ctx)
    warnings: list[WarningItem] = []
    swept = list(snap.swept)
    created = False
    if auto:
        from vasty.commands import reserve
        from vasty.commands.run import auto_ttl

        reserved = reserve.reserve_lease(ctx, args, snap, ttl=auto_ttl(ctx), wait=True)
        lease = reserved.lease
        warnings = list(reserved.result.warnings)
        swept = merge_swept(swept, reserved.result.swept)
        created = not reserved.result.reused
    else:
        lease = pick_lease(ctx, snap, args.on)

    try:
        result = _bring_up(ctx, snap, lease, plan)
    except BaseException:
        if created:
            from vasty.commands.run import release_quietly

            release_quietly(ctx, lease)
        raise
    result.swept = swept
    result.warnings = merge_warnings(warnings, lease_warnings(ctx, snap, lease, ctx.clock.now()))
    return Outcome(result, human=_human(result))


def _public_url(ctx: Context, snap: engine.Snapshot, lease: CachedLease) -> str:
    row = snap.instance(lease.instance_id) or ctx.provider.get_instance(lease.instance_id)
    host = row.public_ipaddr if row is not None else None
    port = (row.ports if row is not None else lease.ports).get(SERVE_PORT) or lease.ports.get(SERVE_PORT)
    if not host or not port:
        raise VastyError(
            "port_mapping_missing",
            f"Lease {lease.lease} has no public mapping for port {SERVE_PORT}.",
            f"Serve on a box reserved by vasty, or tunnel: vasty serve --on {lease.lease} "
            f"--model MODEL --bind-local.",
        )
    return f"http://{host}:{port}/v1"


def _bring_up(ctx: Context, snap: engine.Snapshot, lease: CachedLease, plan: _Plan) -> ServeResult:
    target = engine.ssh_target(lease)
    url = f"http://127.0.0.1:{SERVE_PORT}/v1" if plan.bind_local else _public_url(ctx, snap, lease)
    _preflight(ctx, target, lease, plan.model)

    key = "vasty-" + ctx.random_hex(32)
    host = "127.0.0.1" if plan.bind_local else "0.0.0.0"
    shown = shlex.join(server_argv(plan.model, host, plan.extra))
    command = f"export VLLM_API_KEY={shlex.quote(key)}\n{shown}"
    job = Job(
        id=next_job_id(lease), cmd=shown, started_at=None, exit=None, state="serving",
        kind="serve", port=SERVE_PORT,
    )
    started = ctx.box.start_job(target, job, command)
    save_lease(ctx, lease, lambda record: put_job(record, started))
    _wait_ready(ctx, target, lease, started.id, url, key, plan.bind_local)
    return ServeResult(
        lease=lease.lease,
        job=started.id,
        model=plan.model,
        url=url,
        api_key=key,
        expires_at=iso(effective_expiry(lease.label)),
        warnings=[],
        swept=[],
    )


def _preflight(ctx: Context, target: SshTarget, lease: CachedLease, model: str) -> None:
    """Raise `vllm_missing` when the box has no `vllm` on PATH."""
    done = ctx.box.exec(target, PREFLIGHT_COMMAND, timeout=PREFLIGHT_TIMEOUT_S)
    if done.exit != 0:
        raise VastyError(
            "vllm_missing",
            f"Lease {lease.lease} has no vllm on PATH.",
            f"Reserve with a vLLM image: vasty serve --model {model} --image {VLLM_IMAGE}.",
        )


def _ready(ctx: Context, target: SshTarget, url: str, key: str, bind_local: bool) -> bool:
    if bind_local:
        done = ctx.box.exec(target, probe_command(key), timeout=HTTP_TIMEOUT_S + 10)
        return done.stdout.strip() == "200"
    headers = {"Authorization": f"Bearer {key}"}
    return ctx.http_get(url + "/models", headers, HTTP_TIMEOUT_S) == 200


def _wait_ready(
    ctx: Context,
    target: SshTarget,
    lease: CachedLease,
    job_id: str,
    url: str,
    key: str,
    bind_local: bool,
) -> None:
    deadline = ctx.mono() + READY_DEADLINE_S
    log_hint = f"Read the log: vasty ssh {lease.lease} -- tail -n 100 /workspace/.vasty/jobs/{job_id}/log"
    while True:
        if _ready(ctx, target, url, key, bind_local):
            return
        status = ctx.box.job_status(target, job_id)
        if status.exit is not None or status.state == "exited":
            code = status.exit
            save_lease(ctx, lease, lambda record: finish_job(record, job_id, code, status.finished_at))
            message = f"vLLM exited {code} before /v1/models answered."
            raise _serve_failed(ctx, target, lease, job_id, key, message, log_hint, code)
        if ctx.mono() >= deadline:
            message = f"/v1/models did not answer within {int(READY_DEADLINE_S)}s."
            error = _serve_failed(ctx, target, lease, job_id, key, message, log_hint, None)
            try:
                ctx.box.signal_job(target, job_id, "TERM")
            except VastyError:
                pass
            raise error
        ctx.sleep(POLL_INTERVAL_S)


def _serve_failed(
    ctx: Context,
    target: SshTarget,
    lease: CachedLease,
    job_id: str,
    key: str,
    message: str,
    hint: str,
    code: int | None,
) -> VastyError:
    """Return `serve_failed` with the job's redacted log tail; a failed read leaves it out."""
    details: dict[str, Any] = {"exit": code, "lease": lease.lease}
    try:
        details["log_tail"] = redact_tail(ctx.box.log_tail(target, job_id, LOG_LINES), key)
    except (VastyError, OSError):
        pass
    return VastyError("serve_failed", message, hint, details=details)


def _human(result: ServeResult) -> str:
    return "\n".join([
        f"Serving {result.model} on {result.lease} (job {result.job})",
        f"url:      {result.url}",
        f"api_key:  {result.api_key}",
        "          This key will not be shown again. Save it now.",
        f"expires:  {result.expires_at}",
    ])
