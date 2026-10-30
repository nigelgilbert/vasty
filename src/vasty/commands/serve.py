"""`vasty serve`.

`serve` maps `--model` to hardware through the `[models."NAME"]` tables.
Without `--on` it resolves settings with the entry's `vram`, `gpu` and
`image` as the `model` layer, below flags the user gave, then reserves a box
with `run_ttl` (or `--ttl`). A model with no entry needs `--vram` and
`--image` to auto-reserve. With `--on` any model name or box path serves.

The box's image supplies vLLM. On the box, `serve` checks for `vllm` on PATH
and raises `vllm_missing` when it is absent. It then starts `vllm serve` as a
`serve` job on port 8000 with a fresh `vasty-` key, and polls `/v1/models`
with that key until it answers 200. With `--bind-local` vLLM listens on
127.0.0.1 and the poll runs on the box with curl. Any failure after the
reserve releases a box this call created.
"""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass

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
from vasty.config import ModelEntry, resolve
from vasty.context import Context
from vasty.errors import VastyError
from vasty.models import SERVE_PORT, CachedLease, Job, ServeResult, WarningItem
from vasty.remote import SshTarget
from vasty.state import effective_expiry
from vasty.timeutil import iso

READY_DEADLINE_S = 1800.0
POLL_INTERVAL_S = 5.0
HTTP_TIMEOUT_S = 5.0
PREFLIGHT_TIMEOUT_S = 30.0
PREFLIGHT_COMMAND = "command -v vllm"
VLLM_IMAGE = "vllm/vllm-openai:v0.32.0"


def model_entry(ctx: Context, model: str) -> ModelEntry | None:
    """Return the model table entry without fixing `ctx.settings`.

    The lookup resolves config without the `startup` flag so `--startup -`
    still reads stdin once, later.
    """
    flags = {k: v for k, v in ctx.flags.items() if k != "startup"}
    settings = resolve(flags, ctx.stdin_json, ctx.profile, ctx.env, ctx.cwd, ctx.home)
    return settings.models.get(model)


def server_argv(model: str, quant: str | None, host: str, key: str | None) -> list[str]:
    """Return the `vllm serve` argv; pass `key` None for the displayed form."""
    argv = ["vllm", "serve", model]
    if key is not None:
        argv += ["--api-key", key]
    argv += ["--host", host, "--port", str(SERVE_PORT)]
    if quant:
        argv += ["--quantization", quant]
    return argv


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
    quant: str | None
    bind_local: bool


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    auto = args.on is None
    entry = model_entry(ctx, args.model)
    if auto:
        if entry is None and (ctx.flags.get("vram") is None or ctx.flags.get("image") is None):
            raise VastyError(
                "model_unknown",
                f"Model {args.model!r} has no [models] entry.",
                f'Pass --vram GB and --image IMAGE, or add [models."{args.model}"] to config.',
            )
        ctx.model = args.model
    quant = args.quant if args.quant is not None else (entry.quant if entry else None)
    plan = _Plan(args.model, quant, bool(args.bind_local))
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
    command = shlex.join(server_argv(plan.model, plan.quant, host, key))
    shown = shlex.join(server_argv(plan.model, plan.quant, host, None))
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
            f"Reserve with a vLLM image: vasty serve --model {model} --image {VLLM_IMAGE}, "
            f'or add image to the [models."{model}"] entry.',
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
            raise VastyError(
                "serve_failed",
                f"vLLM exited {code} before /v1/models answered.",
                log_hint,
                details={"exit": code},
            )
        if ctx.mono() >= deadline:
            try:
                ctx.box.signal_job(target, job_id, "TERM")
            except VastyError:
                pass
            raise VastyError(
                "serve_failed",
                f"/v1/models did not answer within {int(READY_DEADLINE_S)}s.",
                log_hint,
            )
        ctx.sleep(POLL_INTERVAL_S)


def _human(result: ServeResult) -> str:
    return "\n".join([
        f"Serving {result.model} on {result.lease} (job {result.job})",
        f"url:      {result.url}",
        f"api_key:  {result.api_key}",
        "          This key will not be shown again. Save it now.",
        f"expires:  {result.expires_at}",
    ])
