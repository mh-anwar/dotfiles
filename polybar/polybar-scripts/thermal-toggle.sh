#!/bin/bash

STATE="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-thermal"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/polybar-fan.pid"

if [ "$(cat "$STATE" 2>/dev/null)" = "temp" ]; then
    echo fan > "$STATE"
else
    echo temp > "$STATE"
fi

if [ -f "$PIDFILE" ]; then
    kill -USR1 "$(cat "$PIDFILE")" 2>/dev/null
fi
