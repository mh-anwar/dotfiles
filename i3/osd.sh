#!/usr/bin/env bash
# Volume/brightness/mic keys.  osd.sh vol-up|vol-down|mute|mic-mute|bright-up|bright-down
#
# Normally forwards the key to the dashboard process (dev.mohammad.Osd), which
# applies it and shows the Windows-style popup. Key repeat can't queue up
# there. If the dashboard isn't running, apply the change here instead.

gdbus call --session --dest dev.mohammad.Osd --object-path /dev/mohammad/Osd \
    --method dev.mohammad.Osd.Key "$1" >/dev/null 2>&1 && exit 0

# Fallback: drop presses that arrive while one is still running.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/osd.lock"
flock -n 9 || exit 0
case "$1" in
    vol-up)      pactl set-sink-mute @DEFAULT_SINK@ 0
                 cur=$(pactl get-sink-volume @DEFAULT_SINK@ | grep -oP "\d+(?=%)" | head -1)
                 pactl set-sink-volume @DEFAULT_SINK@ "$(( cur + 5 > 153 ? 153 : cur + 5 ))%" ;;
    vol-down)    pactl set-sink-volume @DEFAULT_SINK@ -5% ;;
    mute)        pactl set-sink-mute @DEFAULT_SINK@ toggle ;;
    mic-mute)    pactl set-source-mute @DEFAULT_SOURCE@ toggle ;;
    bright-up)   brightnessctl -d amdgpu_bl1 --exponent=2 --min-value=1500 -q set 5%+ ;;
    bright-down) brightnessctl -d amdgpu_bl1 --exponent=2 --min-value=1500 -q set 5%- ;;
esac
