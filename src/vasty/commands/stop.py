"""`vasty stop LEASE [JOB]`.

`stop` sends TERM to the job's process group and polls its box record for up
to 10s. LEASE resolves like `status`. JOB is implied when one job is live and
required when several are; the `invalid_arguments` error lists the live jobs
in `details.jobs`. A job that exits in the grace is recorded `killed` with the
exit code and finish time the box wrote, so `status` reports the same `exit`
and `duration_s`. A job still running after the grace returns
its live state, `running` or `serving`, and exit code 2.
"""

from __future__ import annotations

import argparse

from vasty import engine, views
from vasty.cli import Outcome
from vasty.commands._common import (
    finish_job,
    lease_warnings,
    pick_lease,
    save_lease,
    signal_and_wait,
)
from vasty.context import Context
from vasty.errors import VastyError
from vasty.models import CachedLease, Job, StopResult
from vasty.state import LIVE_JOB_STATES
from vasty.timeutil import format_duration

STOP_WAIT_S = 10.0
RUNNING_EXIT = 2


def pick_job(lease: CachedLease, job_id: str | None) -> Job:
    """Return the live job to stop, or raise `invalid_arguments` naming the live jobs."""
    live = [job for job in lease.jobs if job.state in LIVE_JOB_STATES]
    ids = [job.id for job in live]
    details = {"lease": lease.lease, "jobs": ids}
    if job_id is not None:
        for job in live:
            if job.id == job_id:
                return job
        listed = ", ".join(ids) if ids else "none"
        raise VastyError(
            "invalid_arguments",
            f"Lease {lease.lease} has no running job {job_id}. Running jobs: {listed}.",
            f"Run vasty status {lease.lease}.",
            details=details,
        )
    if len(live) == 1:
        return live[0]
    if not live:
        raise VastyError(
            "invalid_arguments",
            f"Lease {lease.lease} has no running job.",
            f"Run vasty status {lease.lease}.",
            details=details,
        )
    raise VastyError(
        "invalid_arguments",
        f"Lease {lease.lease} runs {len(ids)} jobs: {', '.join(ids)}.",
        f"Name one: vasty stop {lease.lease} {ids[0]}.",
        details=details,
    )


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    snap = engine.refresh(ctx)
    lease = pick_lease(ctx, snap, args.lease)
    job = pick_job(lease, args.job)
    record = signal_and_wait(ctx, engine.ssh_target(lease), job.id, "TERM", STOP_WAIT_S)
    now = ctx.clock.now()
    running = record.exit is None and record.state in LIVE_JOB_STATES
    if not running:
        code = record.exit
        finished = record.finished_at or now
        save_lease(ctx, lease, lambda found: finish_job(found, job.id, code, finished, "killed"))
    stopped = next(j for j in lease.jobs if j.id == job.id)
    view = views.job_view(record if running else stopped, now, lease.state)
    result = StopResult(
        lease=lease.lease,
        job=view.job,
        cmd=view.cmd,
        state=view.state,
        exit=view.exit,
        duration_s=view.duration_s,
        warnings=lease_warnings(ctx, snap, lease, now),
        swept=list(snap.swept),
    )
    return Outcome(result, exit_code=RUNNING_EXIT if running else 0, human=_human(result, running))


def _human(result: StopResult, running: bool) -> str:
    took = format_duration(result.duration_s or 0)
    if running:
        return (f"{result.job} on {result.lease} still runs {STOP_WAIT_S:g}s after TERM. "
                f"Check it with vasty status {result.lease}.")
    code = "no exit code" if result.exit is None else f"exit {result.exit}"
    return f"Stopped {result.job} on {result.lease}: {code} after {took}"
