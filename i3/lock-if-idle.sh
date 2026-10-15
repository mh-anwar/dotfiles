#!/usr/bin/env bash
# Called by xss-lock when the screen has been idle.  Lock, unless something is
# playing audio or the focused window is fullscreen (video, calls, slides).

if pactl list sink-inputs 2>/dev/null | grep -q 'Corked: no'; then
    xset s reset; exit 0
fi

if i3-msg -t get_tree | python3 -c '
import json, sys
def walk(n):
    if n.get("focused"):
        sys.exit(0 if n.get("fullscreen_mode") else 1)
    for c in n.get("nodes", []) + n.get("floating_nodes", []):
        walk(c)
walk(json.load(sys.stdin)); sys.exit(1)'; then
    xset s reset; exit 0
fi

exec betterlockscreen --lock
