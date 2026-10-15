#!/usr/bin/env bash
# (Re)start the desktop dashboard.  Run from i3 with exec_always, after
# monitors.sh, so it follows layout changes.
# Anchored: only the dashboard itself, not any process that merely mentions the path.
pkill -f "^/usr/bin/python3 $HOME/.config/dashboard/dashboard.py$" 2>/dev/null
sleep 1  # let monitors.sh / feh settle
exec /usr/bin/python3 "$HOME/.config/dashboard/dashboard.py" >/dev/null 2>&1
