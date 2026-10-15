#!/bin/bash

orange="#f4b860"
sun=$'\uf185'
last=""

while true; do
    pct="--"
    for dev in /sys/class/backlight/*; do
        [ -r "$dev/brightness" ] || continue
        read -r cur < "$dev/brightness"
        read -r max < "$dev/max_brightness"
        if [ "$max" -gt 0 ] 2>/dev/null; then
            pct=$((cur * 100 / max))
        fi
        break
    done
    line="$(printf '%%{F%s}%s %s%%{F-}' "$orange" "$sun" "$pct")"
    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
    sleep 2
done
