#!/bin/bash
# vasty watchdog: destroy this box when /workspace/.vasty/clock runs out.
# cron starts a copy every minute; the lock directory keeps one running.
# The watchdog is the only writer of the guard file. Each loop it publishes a full snapshot:
# watchdog when curl is absent, destroy_key when the env lacks the key or the last conclusive key check was refused.
# The key check is one authenticated GET of its own row at start and hourly; 401 or 403 marks the key bad,
# a 2xx marks it good, any other result keeps the last answer. A new process seeds that answer from the file.
# The GET proves the key reads its row; the delete scope is assumed from Vast's container key.
# A 401 or 403 from the DELETE at expiry also marks the key bad, so a read-only key shows up in status.
# VASTY_ROOT, VASTY_API, VASTY_POLL, VASTY_REDESTROY, VASTY_KEYCHECK, VASTY_CURL and VASTY_MAX_LOOPS override the defaults for tests.
R=${VASTY_ROOT:-/workspace/.vasty}
API=${VASTY_API:-https://console.vast.ai/api/v0}
POLL=${VASTY_POLL:-60}
[ "$POLL" -gt 60 ] && POLL=60
AGAIN=${VASTY_REDESTROY:-300}
CHECK=${VASTY_KEYCHECK:-3600}
CURL=${VASTY_CURL:-curl}
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
publish() {
  s=
  [ "$curl_ok" = 1 ] || s="$s watchdog"
  if [ -z "$id" ] || [ -z "$key" ] || [ "$key_state" = bad ]; then s="$s destroy_key"; fi
  printf '%s\n' $s >"$R/guard.tmp.$$" && mv -f "$R/guard.tmp.$$" "$R/guard"
}
key_check() {
  code=$("$CURL" -sS -m 30 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $key" "$API/instances/$id/" 2>/dev/null)
  case $code in
  401 | 403)
    key_state=bad
    log "key check: HTTP $code"
    ;;
  2[0-9][0-9])
    key_state=ok
    ;;
  esac
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
checked=
key_state=
grep -qx destroy_key "$R/guard" 2>/dev/null && key_state=bad
while :; do
  curl_ok=0
  command -v "$CURL" >/dev/null 2>&1 && curl_ok=1
  id=$(sed -n 's/^CONTAINER_ID=//p' "$R/env" 2>/dev/null | head -n 1)
  key=$(sed -n 's/^CONTAINER_API_KEY=//p' "$R/env" 2>/dev/null | head -n 1)
  publish
  touch "$R/alive"
  exp=$(cat "$R/clock" 2>/dev/null)
  now=$(date +%s)
  if [ -n "$id" ] && [ -n "$key" ] && { [ -z "$checked" ] || [ $((now - checked)) -ge "$CHECK" ]; }; then
    checked=$now
    key_check
    publish
  fi
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
    elif code=$("$CURL" -fsS -m 30 -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer $key" "$API/instances/$id/"); then
      log "clock expired at $exp; destroy accepted"
      done_at=$now
      back=0
    else
      case $code in
      401 | 403)
        key_state=bad
        publish
        ;;
      esac
      back=$((back ? back * 2 : 2))
      [ "$back" -gt 60 ] && back=60
      log "clock expired at $exp; destroy failed; HTTP $code; retry in ${back}s"
      s=$back
    fi
    ;;
  esac
  sleep "$s"
  n=$((n + 1))
  [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ] && break
done
