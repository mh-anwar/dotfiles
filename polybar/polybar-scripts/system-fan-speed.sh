#!/bin/bash

STATE="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-thermal"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/polybar-fan.pid"
cyan="#67d4f0"
orange="#f4b860"
fan_icon=$'\uf863'
temp_icon=$'\uf2c7'

render() {
    mode=$(cat "$STATE" 2>/dev/null || echo fan)
    if [ "$mode" = "temp" ]; then
        temp=$(sensors 2>/dev/null | awk -F'[+ ]+' '/Tctl|Package id 0/{print $2; exit}')
        [ -z "$temp" ] && temp=$(sensors 2>/dev/null | awk -F'[+ ]+' '/CPU:/{print $2; exit}')
        [ -z "$temp" ] && temp="--"
        line="$(printf '%%{F%s}%s %s%%{F-}' "$orange" "$temp_icon" "$temp")"
    else
        rpm=$(sensors 2>/dev/null | awk '/Processor Fan/{print $3; exit}')
        if [ -n "$rpm" ]; then
            value=$(awk -v r="$rpm" 'BEGIN{printf "%.1fk", r / 1000}')
        else
            value="--"
        fi
        line="$(printf '%%{F%s}%s %s%%{F-}' "$cyan" "$fan_icon" "$value")"
    fi
    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
}

last=""
trap 'render' USR1
trap 'rm -f "$PIDFILE"' EXIT
echo $$ > "$PIDFILE"
render

while true; do
    sleep 15 &
    wait $! 2>/dev/null
    rc=$?
    [ "$rc" -gt 128 ] && continue
    render
done
