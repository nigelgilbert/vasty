"""The `onstart` script, startup wrapper and on-box watchdog.

`build_onstart` returns the shell command Vast runs when the container starts.
It decodes a gzip and base64 payload and pipes it to bash. The payload writes
the clock file, the env file and the guard file under `/workspace/.vasty`,
starts the watchdog under cron and `nohup`, then runs the user's startup
script once through a wrapper that writes `startup.started`, `startup.exit`
and `startup.log`.

The default image carries the watchdog at `IMAGE_WATCHDOG`. With a custom
image the payload also carries the watchdog and an essentials installer. A
custom image that lacks root or needs packages without apt-get gets an
`unsupported` file listing what it lacks; a missing bash writes `bash` there.
The probe reports that file as `ProbeResult.unsupported`, and callers map a
non-empty list to `image_unsupported`.

The builders take the box paths as keyword arguments so tests can run the
generated scripts in a temp directory.
"""

from __future__ import annotations

import base64
import gzip
import shlex
from importlib import resources

from vasty.errors import VastyError

ONSTART_LIMIT = 4048
ROOT = "/workspace/.vasty"
WORKDIR = "/workspace"
IMAGE_WATCHDOG = "/opt/vasty/watchdog.sh"
PROC_ENVIRON = "/proc/1/environ"
STARTUP_INTERRUPTED = -1
"""The `startup.exit` value for a hook cut off by a container restart."""

LAYERS = ("watchdog", "destroy_key", "clock_file")
ESSENTIALS: tuple[tuple[str, str], ...] = (
    ("sshd", "openssh-server"),
    ("cron", "cron"),
    ("rsync", "rsync"),
    ("tmux", "tmux"),
    ("curl", "curl"),
    ("python3", "python3"),
)
"""Commands vasty needs on the box, each with the apt package that provides it."""


def watchdog_script() -> str:
    """Return the watchdog shell script installed at `/workspace/.vasty/watchdog.sh`."""
    return resources.files("vasty").joinpath("scripts/watchdog.sh").read_text(encoding="utf-8")


def _compact(script: str) -> str:
    """Drop comment lines and indentation from a script without heredocs."""
    lines = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or (stripped.startswith("#") and not stripped.startswith("#!")):
            continue
        lines.append(stripped)
    return "\n".join(lines) + "\n"


def _delimiter(text: str, base: str) -> str:
    """Return a heredoc delimiter that no line of `text` equals."""
    lines = set(text.splitlines())
    delim = base
    n = 0
    while delim in lines:
        n += 1
        delim = f"{base}_{n}"
    return delim


def _heredoc(path: str, text: str, base: str) -> str:
    body = text if text.endswith("\n") else text + "\n"
    delim = _delimiter(body, base)
    return f"cat>{path}<<'{delim}'\n{body}{delim}\n"


def _head(root: str, workdir: str, watchdog: str) -> str:
    return (
        f"R={shlex.quote(root)};W={shlex.quote(workdir)};WD={shlex.quote(watchdog)};"
        'export VASTY_ROOT="$R"\n'
        'mkdir -p "$R/jobs";chmod 700 "$R";g=\n'
    )


def _env_part(proc_environ: str) -> str:
    """Copy `CONTAINER_ID` and `CONTAINER_API_KEY` to the env file and flag a missing key."""
    return (
        f"pe(){{ tr '\\0' '\\n' 2>/dev/null<{shlex.quote(proc_environ)}|"
        'sed -n "s/^$1=//p"|head -n1;}\n'
        "ci=${CONTAINER_ID:-$(pe CONTAINER_ID)};ck=${CONTAINER_API_KEY:-$(pe CONTAINER_API_KEY)}\n"
        'if [ -n "$ci" ]&&[ -n "$ck" ];then(umask 077;'
        "printf 'CONTAINER_ID=%s\\nCONTAINER_API_KEY=%s\\n' \"$ci\" \"$ck\">\"$R/env.tmp\")"
        '&&mv -f "$R/env.tmp" "$R/env";fi\n'
        '[ -e "$R/env" ]&&chmod 600 "$R/env"\n'
        "grep -q '^CONTAINER_ID=.' \"$R/env\" 2>/dev/null&&"
        "grep -q '^CONTAINER_API_KEY=.' \"$R/env\"||g=\"$g destroy_key\"\n"
    )


def _installer(apt: str, essentials: tuple[tuple[str, str], ...]) -> str:
    """Install missing essentials with apt-get and record what the image lacks.

    `p` lists the packages for missing essentials. A missing essential on an
    image without apt-get adds `apt-get` to `unsupported`.
    """
    pairs = " ".join(f"{cmd}:{pkg}" for cmd, pkg in essentials)
    a = shlex.quote(apt)
    return (
        f"u=;p=;for e in {pairs};do c=${{e%%:*}};"
        'command -v $c>/dev/null||[ -x /usr/sbin/$c ]||p="$p ${e#*:}";done\n'
        '[ "$(id -u)" = 0 ]||u="$u root"\n'
        f'if command -v {a}>/dev/null;then if [ -n "$p" ];then '
        f"export DEBIAN_FRONTEND=noninteractive;{a} update -qq>>\"$R/install.log\" 2>&1;"
        f"{a} install -y -qq --no-install-recommends $p>>\"$R/install.log\" 2>&1||"
        'echo "install failed:$p">>"$R/install.log";fi\n'
        'elif [ -n "$p" ];then u="$u apt-get";fi\n'
        'if [ -n "$u" ];then printf \'%s\\n\' $u>"$R/unsupported";else rm -f "$R/unsupported";fi\n'
    )


def _watchdog_part(services: bool, alive_wait: float, keep_running: bool = False) -> str:
    """Start the watchdog under cron and `nohup` and flag it when `alive` does not appear.

    At container start the lock and `alive` belong to a dead process, so the
    script clears them. With `keep_running`, a live lock holder stays and no
    second copy starts.
    """
    tries = max(1, int(alive_wait / 0.2))
    out = ""
    if services:
        out += (
            'if [ -d /etc/cron.d ];then echo "* * * * * root VASTY_ROOT=$R /bin/bash $WD'
            '>>$R/watchdog.log 2>&1">/etc/cron.d/vasty;chmod 644 /etc/cron.d/vasty;fi\n'
            "(service cron start||cron)>/dev/null 2>&1\n"
            "[ -x /usr/sbin/sshd ]&&{ mkdir -p /run/sshd;/usr/sbin/sshd>/dev/null 2>&1;}\n"
        )
    start = (
        'rm -rf "$R/watchdog.lock" "$R/alive"\n'
        'if [ -f "$WD" ];then nohup bash "$WD">>"$R/watchdog.log" 2>&1 </dev/null & fi\n'
    )
    if keep_running:
        start = (
            'wp=$(cat "$R/watchdog.lock/pid" 2>/dev/null)\n'
            'if [ -z "$wp" ]||! kill -0 "$wp" 2>/dev/null;then\n' + start + "fi\n"
        )
    out += start
    out += (
        f'i=0;while [ ! -e "$R/alive" ]&&[ $i -lt {tries} ];do sleep 0.2;i=$((i+1));done\n'
        '[ -e "$R/alive" ]||g="$g watchdog"\n'
    )
    return out


_GUARD_WRITE = "printf '%s\\n' $g>\"$R/guard.tmp\";mv -f \"$R/guard.tmp\" \"$R/guard\"\n"


def _startup_part(startup: str | None) -> str:
    """Run the user's startup once and record started and exit markers."""
    out = 'cd "$W" 2>/dev/null||cd /\nif [ ! -e "$R/startup.started" ];then\n'
    if startup is not None and startup.strip():
        out += _heredoc('"$R/startup.sh"', startup, "VASTY_STARTUP_EOF")
        out += (
            'date +%s>"$R/startup.started"\n'
            "nohup bash -c 'bash \"$1/startup.sh\">>\"$1/startup.log\" 2>&1 </dev/null;"
            'echo $? >"$1/startup.exit.tmp";mv -f "$1/startup.exit.tmp" "$1/startup.exit"\''
            ' vasty "$R">/dev/null 2>&1 </dev/null &\n'
        )
    else:
        out += 'date +%s>"$R/startup.started";echo 0 >"$R/startup.exit"\n'
    out += (
        'elif [ ! -e "$R/startup.exit" ];then '
        'echo "vasty: startup cut off by a container restart">>"$R/startup.log";'
        f'echo {STARTUP_INTERRUPTED} >"$R/startup.exit"\nfi\n'
    )
    return out


def build_payload(
    ttl: int,
    startup: str | None,
    custom_image: bool,
    *,
    root: str = ROOT,
    workdir: str = WORKDIR,
    watchdog_path: str | None = None,
    services: bool = True,
    apt: str = "apt-get",
    essentials: tuple[tuple[str, str], ...] = ESSENTIALS,
    proc_environ: str = PROC_ENVIRON,
    alive_wait: float = 10.0,
) -> str:
    """Return the bash script that `onstart` decodes and runs.

    The clock file gets `now + ttl` only when it is absent or empty, so a
    container restart keeps an extended value. Missing guard layers go to the
    guard file one per line. The whole script sits in one brace group so bash
    parses it before any command reads stdin.
    """
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    if watchdog_path is None:
        watchdog_path = f"{root}/watchdog.sh" if custom_image else IMAGE_WATCHDOG
    body = _head(root, workdir, watchdog_path)
    body += (
        f'[ -s "$R/clock" ]||{{ echo $(($(date +%s)+{int(ttl)})) >"$R/clock.tmp"'
        '&&mv -f "$R/clock.tmp" "$R/clock";}\n'
    )
    body += _env_part(proc_environ)
    if custom_image:
        body += _installer(apt, essentials)
        body += _heredoc('"$WD.tmp"', _compact(watchdog_script()), "VASTY_WATCHDOG_EOF")
        body += 'mv -f "$WD.tmp" "$WD"\n'
    body += _watchdog_part(services, alive_wait)
    body += _GUARD_WRITE
    body += _startup_part(startup)
    return "{\n" + body + "} </dev/null\n"


def encode_payload(payload: str, custom_image: bool, root: str = ROOT) -> str:
    """Wrap a payload in the `onstart` command that decodes and runs it."""
    data = base64.b64encode(gzip.compress(payload.encode("utf-8"), compresslevel=9, mtime=0))
    cmd = f"echo {data.decode('ascii')}|base64 -d|gunzip|bash"
    if custom_image:
        r = shlex.quote(root)
        cmd = f"command -v bash >/dev/null||{{ mkdir -p {r};echo bash>{r}/unsupported;exit 1;}};" + cmd
    return cmd


def decode_onstart(command: str) -> str:
    """Return the payload inside an `onstart` command built by `build_onstart`."""
    end = command.rindex("|base64 -d")
    start = command.rindex("echo ", 0, end) + len("echo ")
    return gzip.decompress(base64.b64decode(command[start:end])).decode("utf-8")


def build_onstart(ttl: int, startup: str | None, custom_image: bool) -> str:
    """Build the encoded `onstart` command.

    Include the clock-file write, the env file, the startup wrapper and the
    user's script, compressed with gzip and base64. With a custom image, also
    include the watchdog and the essentials installer. Raise
    `startup_too_large` when the result exceeds 4048 characters.
    """
    cmd = encode_payload(build_payload(ttl, startup, custom_image), custom_image)
    if len(cmd) > ONSTART_LIMIT:
        raise VastyError(
            "startup_too_large",
            f"The encoded onstart is {len(cmd)} characters; Vast allows {ONSTART_LIMIT}.",
            "Move setup steps into a script you fetch from the box, or use the default image.",
            details={"size": len(cmd), "limit": ONSTART_LIMIT},
        )
    return cmd


def adopt_script(
    expires: int,
    *,
    root: str = ROOT,
    workdir: str = WORKDIR,
    services: bool = True,
    proc_environ: str = PROC_ENVIRON,
    alive_wait: float = 10.0,
) -> str:
    """Return the bash script `tag` runs over SSH to give an orphan a guard.

    It writes the `adopted` marker and the clock file, copies the container
    env from `/proc/1/environ`, installs the watchdog at
    `/workspace/.vasty/watchdog.sh`, starts it under cron and `nohup`, and marks
    startup done. It prints `missing=` followed by the layers still missing.
    """
    body = _head(root, workdir, f"{root}/watchdog.sh")
    body += ': >"$R/adopted"\n'
    body += (
        f'echo {int(expires)} >"$R/clock.tmp"&&mv -f "$R/clock.tmp" "$R/clock"\n'
        f'[ "$(cat "$R/clock" 2>/dev/null)" = {int(expires)} ]||g="$g clock_file"\n'
    )
    body += _env_part(proc_environ)
    body += _heredoc('"$WD.tmp"', watchdog_script(), "VASTY_WATCHDOG_EOF")
    body += 'mv -f "$WD.tmp" "$WD"\n'
    body += _watchdog_part(services, alive_wait, keep_running=True)
    body += 'command -v curl>/dev/null||case "$g" in *watchdog*);;*)g="$g watchdog";;esac\n'
    body += _GUARD_WRITE
    body += '[ -e "$R/startup.started" ]||date +%s>"$R/startup.started"\n'
    body += '[ -e "$R/startup.exit" ]||echo 0 >"$R/startup.exit"\n'
    body += 'echo "missing=$g"\n'
    return "{\n" + body + "} </dev/null\n"
