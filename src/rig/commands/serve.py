"""`rig serve` (spec §4.7, §5.1).

`serve` maps `--model` to hardware through the `[models."NAME"]` tables.
Without `--on` it resolves settings with the entry's `vram`, `gpu` and
`image` as the `model` layer, below flags the user gave, then reserves a box
with `run_ttl` (or `--ttl`). A model with no entry needs `--vram` and
`--image` to auto-reserve. With `--on` any model name or box path serves.

On the box, `serve` installs the pinned vLLM into `/workspace/.rig/venv` when
absent, starts `vllm serve` as a `serve` job on port 8000 with a fresh
`rig-` key, and polls `/v1/models` with that key until it answers 200. The
pin is the version in the model entry's image tag, else `DEFAULT_VLLM`. With
`--bind-local` vLLM listens on 127.0.0.1 and the poll runs on the box with
curl. Any failure after the reserve releases a box this call created.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
from dataclasses import dataclass

from rig import engine
from rig.cli import Outcome
from rig.commands._common import (
    finish_job,
    lease_warnings,
    merge_warnings,
    next_job_id,
    pick_lease,
    put_job,
    require_tools,
    save_lease,
)
from rig.config import ModelEntry, resolve
from rig.context import Context
from rig.errors import RigError
from rig.models import CachedLease, Job, ServeResult, WarningItem
from rig.remote import BoxUnreachableError, SshTarget
from rig.state import effective_expiry
from rig.timeutil import iso

PORT = 8000
VENV = "/workspace/.rig/venv"
DEFAULT_VLLM = "0.6.3"
INSTALL_TIMEOUT_S = 1800.0
READY_DEADLINE_S = 1800.0
POLL_INTERVAL_S = 5.0
HTTP_TIMEOUT_S = 5.0
INSTALL_HINT = "Check the box with rig ssh LEASE, or pass --image with vLLM preinstalled."
_TAG_VERSION = re.compile(r"v?([0-9]+(?:\.[0-9]+)*(?:\.post[0-9]+)?)")


def model_entry(ctx: Context, model: str) -> ModelEntry | None:
    """Return the model table entry without fixing `ctx.settings`.

    The lookup resolves config without the `startup` flag so `--startup -`
    still reads stdin once, later.
    """
    flags = {k: v for k, v in ctx.flags.items() if k != "startup"}
    settings = resolve(flags, ctx.stdin_json, ctx.profile, ctx.env, ctx.cwd, ctx.home)
    return settings.models.get(model)


def resolve_with_model(ctx: Context, model: str) -> None:
    """Fix `ctx.settings` with the model's entry as the `model` layer below the flags."""
    ctx._settings = resolve(
        ctx.flags, ctx.stdin_json, ctx.profile, ctx.env, ctx.cwd, ctx.home,
        stdin_text=ctx.stdin.read, model=model,
    )


def vllm_pin(entry: ModelEntry | None) -> str:
    """Return the vLLM version from the entry's image tag, else `DEFAULT_VLLM`."""
    if entry is None or entry.image is None or ":" not in entry.image:
        return DEFAULT_VLLM
    match = _TAG_VERSION.fullmatch(entry.image.rsplit(":", 1)[1])
    return match.group(1) if match else DEFAULT_VLLM


def install_command(pin: str) -> str:
    """Return the shell that installs `vllm==PIN` into the venv unless that version is present."""
    v = shlex.quote(VENV)
    spec = shlex.quote(f"vllm=={pin}")
    marker = shlex.quote(pin)
    return (
        f"V={v}; "
        f'if [ -x "$V/bin/vllm" ] && [ "$(cat "$V/.rig-vllm" 2>/dev/null)" = {marker} ]; '
        "then echo rig_venv=present; "
        f'else python3 -m venv "$V" && "$V/bin/pip" install -q {spec} '
        f'&& echo {marker} >"$V/.rig-vllm" && echo rig_venv=installed; fi'
    )


def server_argv(model: str, quant: str | None, host: str, key: str | None) -> list[str]:
    """Return the `vllm serve` argv; pass `key` None for the displayed form."""
    argv = [f"{VENV}/bin/vllm", "serve", model]
    if key is not None:
        argv += ["--api-key", key]
    argv += ["--host", host, "--port", str(PORT)]
    if quant:
        argv += ["--quantization", quant]
    return argv


def probe_command(key: str) -> str:
    """Return the curl command that prints the HTTP status of the box-local `/v1/models`."""
    url = f"http://127.0.0.1:{PORT}/v1/models"
    return (
        f"curl -s -o /dev/null -m {int(HTTP_TIMEOUT_S)} -w '%{{http_code}}' "
        f"-H {shlex.quote('Authorization: Bearer ' + key)} {url}"
    )


@dataclass
class _Plan:
    model: str
    quant: str | None
    entry: ModelEntry | None
    bind_local: bool


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    auto = args.on is None
    entry = model_entry(ctx, args.model)
    if auto:
        if entry is None and (ctx.flags.get("vram") is None or ctx.flags.get("image") is None):
            raise RigError(
                "model_unknown",
                f"Model {args.model!r} has no [models] entry.",
                f'Pass --vram GB and --image IMAGE, or add [models."{args.model}"] to config.',
            )
        resolve_with_model(ctx, args.model)
    quant = args.quant if args.quant is not None else (entry.quant if entry else None)
    plan = _Plan(args.model, quant, entry, bool(args.bind_local))
    require_tools(ctx, "ssh")

    snap = engine.refresh(ctx)
    warnings: list[WarningItem] = []
    created = False
    if auto:
        from rig.commands import reserve
        from rig.commands.run import auto_ttl

        reserved = reserve.reserve_lease(ctx, args, snap, ttl=auto_ttl(ctx), wait=True)
        lease = reserved.lease
        warnings = list(reserved.result.warnings)
        created = not reserved.result.reused
    else:
        lease = pick_lease(ctx, snap, args.on)

    try:
        result = _bring_up(ctx, snap, lease, plan)
    except BaseException:
        if created:
            from rig.commands.run import release_quietly

            release_quietly(ctx, lease)
        raise
    result.warnings = merge_warnings(warnings, lease_warnings(ctx, snap, lease, ctx.clock.now()))
    return Outcome(result, human=_human(result))


def _public_url(ctx: Context, snap: engine.Snapshot, lease: CachedLease) -> str:
    row = snap.instance(lease.instance_id) or ctx.provider.get_instance(lease.instance_id)
    host = row.public_ipaddr if row is not None else None
    port = (row.ports if row is not None else lease.ports).get(PORT) or lease.ports.get(PORT)
    if not host or not port:
        raise RigError(
            "port_mapping_missing",
            f"Lease {lease.lease} has no public mapping for port {PORT}.",
            f"Serve on a box reserved by rig, or tunnel: rig serve --on {lease.lease} "
            f"--model MODEL --bind-local.",
        )
    return f"http://{host}:{port}/v1"


def _bring_up(ctx: Context, snap: engine.Snapshot, lease: CachedLease, plan: _Plan) -> ServeResult:
    target = engine.ssh_target(lease)
    url = f"http://127.0.0.1:{PORT}/v1" if plan.bind_local else _public_url(ctx, snap, lease)
    _install(ctx, target, vllm_pin(plan.entry))

    key = "rig-" + ctx.random_hex(32)
    host = "127.0.0.1" if plan.bind_local else "0.0.0.0"
    command = shlex.join(server_argv(plan.model, plan.quant, host, key))
    shown = shlex.join(server_argv(plan.model, plan.quant, host, None))
    job = Job(
        id=next_job_id(lease), cmd=shown, started_at=None, exit=None, state="serving",
        kind="serve", port=PORT,
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
        swept=list(snap.swept),
    )


def _install(ctx: Context, target: SshTarget, pin: str) -> None:
    """Install the pinned vLLM. Raise `serve_failed` on a non-zero exit or a timeout.

    `SshBox` reports a timeout as `BoxUnreachableError` caused by
    `subprocess.TimeoutExpired`. A lost connection carries no such cause and
    stays `box_unreachable`.
    """
    try:
        done = ctx.box.exec(target, install_command(pin), timeout=INSTALL_TIMEOUT_S)
    except BoxUnreachableError as err:
        if not isinstance(err.__cause__, subprocess.TimeoutExpired):
            raise
        raise RigError(
            "serve_failed",
            f"Installing vllm=={pin} into {VENV} did not finish within {int(INSTALL_TIMEOUT_S)}s.",
            INSTALL_HINT,
            details={"timeout_s": int(INSTALL_TIMEOUT_S)},
        ) from err
    if done.exit != 0:
        detail = (done.stderr.strip() or done.stdout.strip()).splitlines()[-5:]
        raise RigError(
            "serve_failed",
            f"Installing vllm=={pin} into {VENV} exited {done.exit}.",
            INSTALL_HINT,
            details={"exit": done.exit, "output": detail},
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
    log_hint = f"Read the log: rig ssh {lease.lease} -- tail -n 100 /workspace/.rig/jobs/{job_id}/log"
    while True:
        if _ready(ctx, target, url, key, bind_local):
            return
        status = ctx.box.job_status(target, job_id)
        if status.exit is not None or status.state == "exited":
            code = status.exit
            save_lease(ctx, lease, lambda record: finish_job(record, job_id, code, status.finished_at))
            raise RigError(
                "serve_failed",
                f"vLLM exited {code} before /v1/models answered.",
                log_hint,
                details={"exit": code},
            )
        if ctx.mono() >= deadline:
            try:
                ctx.box.signal_job(target, job_id, "TERM")
            except RigError:
                pass
            raise RigError(
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
