#!/bin/bash
# vasty watchdog: destroy this box when /workspace/.vasty/clock runs out.
# cron starts a copy every minute; the lock directory keeps one running.
# VASTY_ROOT, VASTY_API, VASTY_POLL, VASTY_REDESTROY and VASTY_MAX_LOOPS override the defaults for tests.
R=${VASTY_ROOT:-/workspace/.vasty}
API=${VASTY_API:-https://console.vast.ai/api/v0}
POLL=${VASTY_POLL:-60}
[ "$POLL" -gt 60 ] && POLL=60
AGAIN=${VASTY_REDESTROY:-300}
MAX=${VASTY_MAX_LOOPS:-0}
L=$R/watchdog.lock
log() { echo "vasty-watchdog $(date +%s) $*"; }
held() {
  p=$(cat "$L/pid" 2>/dev/null)
  [ -z "$p" ] && return 0
  kill -0 "$p" 2>/dev/null || return 1
  [ -r "/proc/$p/cmdline" ] || return 0
  tr '\0' ' ' <"/proc/$p/cmdline" | grep -q watchdog
}
guard_add() {
  grep -qx "$1" "$R/guard" 2>/dev/null && return
  { cat "$R/guard" 2>/dev/null; echo "$1"; } >"$R/guard.tmp.$$" && mv -f "$R/guard.tmp.$$" "$R/guard"
}
mkdir -p "$R" || exit 1
if ! mkdir "$L" 2>/dev/null; then
  held && exit 0
  rm -rf "$L"
  mkdir "$L" 2>/dev/null || exit 0
fi
echo $$ >"$L/pid"
trap 'rm -rf "$L"' EXIT
n=0
back=0
done_at=0
while :; do
  touch "$R/alive"
  id=$(sed -n 's/^CONTAINER_ID=//p' "$R/env" 2>/dev/null | head -n 1)
  key=$(sed -n 's/^CONTAINER_API_KEY=//p' "$R/env" 2>/dev/null | head -n 1)
  [ -n "$id" ] && [ -n "$key" ] || guard_add destroy_key
  exp=$(cat "$R/clock" 2>/dev/null)
  now=$(date +%s)
  s=$POLL
  case $exp in
  '' | *[!0-9]*)
    log "clock file unreadable"
    ;;
  *)
    if [ "$exp" -gt "$now" ]; then
      back=0
      [ $((exp - now)) -lt "$POLL" ] && s=$((exp - now))
    elif [ -z "$id" ] || [ -z "$key" ]; then
      log "clock expired at $exp; no destroy key"
    elif [ "$done_at" -gt 0 ] && [ $((now - done_at)) -lt "$AGAIN" ]; then
      :
    elif curl -fsS -m 30 -X DELETE -H "Authorization: Bearer $key" "$API/instances/$id/" >/dev/null; then
      log "clock expired at $exp; destroy accepted"
      done_at=$now
      back=0
    else
      back=$((back ? back * 2 : 2))
      [ "$back" -gt 60 ] && back=60
      log "clock expired at $exp; destroy failed; retry in ${back}s"
      s=$back
    fi
    ;;
  esac
  sleep "$s"
  n=$((n + 1))
  [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ] && break
done
