#!/bin/bash

STATE="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-clock"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/polybar-clock.pid"
last=""

render() {
    mode=$(cat "$STATE" 2>/dev/null || echo minute)
    if [ "$mode" = "seconds" ]; then
        line=$(printf '%(%H:%M:%S)T' -1)
    else
        line=$(printf '%(%H:%M)T' -1)
    fi
    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
}

next_wait() {
    efrac=${EPOCHREALTIME#*.}
    efrac=${efrac:0:2}
    [ -z "$efrac" ] && efrac=0
    efrac=$((10#$efrac))
    now=${EPOCHREALTIME%.*}
    mode=$(cat "$STATE" 2>/dev/null || echo minute)
    if [ "$mode" = "seconds" ]; then
        wait_h=$((100 - efrac))
    else
        wait_h=$(((60 - (now % 60)) * 100 - efrac))
    fi
    [ "$wait_h" -lt 1 ] && wait_h=1
    printf '%d.%02d' "$((wait_h / 100))" "$((wait_h % 100))"
}

trap ':' USR1
trap 'rm -f "$PIDFILE"' EXIT
echo $$ > "$PIDFILE"
render

while true; do
    sleep "$(next_wait)" &
    wait $! 2>/dev/null
    render
done
