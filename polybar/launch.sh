#!/usr/bin/env bash

# 1. Kill all existing polybar processes
# Using pkill is fine, but we use the -u $USER flag to be safe
pkill -u $USER -x polybar

# 2. WAIT loop (Crucial Step)
# This prevents launching new bars until the old ones have actually exited
while pgrep -u $UID -x polybar >/dev/null; do sleep 1; done

# 3. Launch the bar on all connected monitors
if type "xrandr" > /dev/null; then
  for m in $(xrandr --query | grep " connected" | cut -d" " -f1); do
    MONITOR=$m polybar --reload the_one_bar &
  done
else
  polybar --reload the_one_bar &
fi
