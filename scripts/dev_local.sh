#!/usr/bin/env bash
#
# dev_local.sh — start / stop / check the local dev stack.
#
# WHY THIS EXISTS
# ---------------
# The two servers kept dying. Not crashing — being *killed*, because a process
# started from an agent session is a child of that session's process group, so it
# goes when the group goes. Restarting it the same way just repeats the loop.
#
# The fix is to put each server in its OWN session and process group, so it is
# not signalled when the launching group goes. On Linux that is `setsid(1)` —
# but **macOS does not ship setsid**, so this uses Python's os.setsid(), which is
# the same syscall, via a two-line exec shim. Combined with `nohup` (ignore
# SIGHUP) they then behave like any normal background service: running until
# something explicitly stops them, or the machine reboots.
#
# WHY SESSION_COOKIE_SECURE=0 IS SET HERE
# ---------------------------------------
# Without it the session cookie is issued with the Secure flag, and browsers
# refuse to store a Secure cookie over plain http. Sign-in then appears to do
# nothing at all — the request succeeds, the cookie is dropped silently, and the
# next request arrives anonymous. It is the single most confusing local failure
# in this feature, so the default here is the one that works.
#
# USAGE
#   bash scripts/dev_local.sh start     # backend :8000 + Vite :5173
#   bash scripts/dev_local.sh stop
#   bash scripts/dev_local.sh status
#   bash scripts/dev_local.sh restart

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
LOG_DIR="/tmp"
BACKEND_LOG="$LOG_DIR/finex_backend.log"
FRONTEND_LOG="$LOG_DIR/finex_vite.log"

pid_on() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

# setsid(1) is Linux-only. Python's os.setsid() is the identical syscall and
# python3 is always present here, so this shim works on both.
if command -v setsid >/dev/null 2>&1; then
    DETACH=(setsid)
else
    DETACH=(python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])')
fi

start_backend() {
    if [ -n "$(pid_on $BACKEND_PORT)" ]; then
        echo "  backend  already running on :$BACKEND_PORT"
        return
    fi
    cd "$ROOT/webapp/backend"
    SESSION_COOKIE_SECURE=0 \
    PUBLIC_BASE_URL="http://localhost:$BACKEND_PORT" \
    nohup "${DETACH[@]}" "$ROOT/.venv/bin/python" -m uvicorn main:app \
        --host 0.0.0.0 --port "$BACKEND_PORT" > "$BACKEND_LOG" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    echo "  backend  starting on :$BACKEND_PORT  (log: $BACKEND_LOG)"
}

start_frontend() {
    if [ -n "$(pid_on $FRONTEND_PORT)" ]; then
        echo "  frontend already running on :$FRONTEND_PORT"
        return
    fi
    cd "$ROOT/webapp/frontend"
    nohup "${DETACH[@]}" npm run dev > "$FRONTEND_LOG" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    echo "  frontend starting on :$FRONTEND_PORT (log: $FRONTEND_LOG)"
}

stop_one() {
    local port="$1" name="$2" pid
    pid="$(pid_on "$port")"
    if [ -z "$pid" ]; then echo "  $name not running"; return; fi
    # Kill the whole process group: `npm run dev` spawns vite as a child, and
    # killing only the parent leaves the port held by an orphan.
    local pgid
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [ -n "$pgid" ]; then kill -TERM -"$pgid" 2>/dev/null || kill "$pid" 2>/dev/null
    else kill "$pid" 2>/dev/null; fi
    echo "  $name stopped (pid $pid)"
}

status() {
    local b f
    b="$(pid_on $BACKEND_PORT)"; f="$(pid_on $FRONTEND_PORT)"
    printf "  backend  :%s  %s\n" "$BACKEND_PORT"  "${b:+running (pid $b)}"
    [ -z "$b" ] && printf "  backend  :%s  NOT RUNNING\n" "$BACKEND_PORT"
    printf "  frontend :%s  %s\n" "$FRONTEND_PORT" "${f:+running (pid $f)}"
    [ -z "$f" ] && printf "  frontend :%s  NOT RUNNING\n" "$FRONTEND_PORT"
    if [ -n "$f" ]; then
        printf "  http://localhost:%s/signin -> %s\n" "$FRONTEND_PORT" \
            "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$FRONTEND_PORT/signin)"
        printf "  /api proxied              -> %s (401 = up, anonymous)\n" \
            "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$FRONTEND_PORT/api/auth/me)"
    fi
}

case "${1:-status}" in
    start)   start_backend; start_frontend; sleep 8; echo; status ;;
    stop)    stop_one $FRONTEND_PORT frontend; stop_one $BACKEND_PORT backend ;;
    restart) stop_one $FRONTEND_PORT frontend; stop_one $BACKEND_PORT backend
             sleep 2; start_backend; start_frontend; sleep 8; echo; status ;;
    status)  status ;;
    *) echo "usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
