#!/bin/bash

STATE="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-clock"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/polybar-clock.pid"

if [ "$(cat "$STATE" 2>/dev/null)" = "seconds" ]; then
    echo minute > "$STATE"
else
    echo seconds > "$STATE"
fi

if [ -f "$PIDFILE" ]; then
    kill -USR1 "$(cat "$PIDFILE")" 2>/dev/null
fi
