#!/bin/bash

DOWN_COLOR="#6fdc9b"
UP_COLOR="#8ab4f8"
DIM="#52525b"

default_iface() {
    while read -r iface dest _; do
        if [ "$dest" = "00000000" ]; then
            printf '%s' "$iface"
            return
        fi
    done < /proc/net/route
}

prev_rx=0
prev_tx=0
prev_time=0
last=""

while true; do
    now=$(printf '%(%s)T' -1)
    iface=$(default_iface)
    if [ -z "$iface" ] || [ ! -d "/sys/class/net/$iface" ]; then
        line="$(printf '%%{F%s}offline%%{F-}' "$DIM")"
        prev_time=0
    else
        read -r rx < "/sys/class/net/$iface/statistics/rx_bytes"
        read -r tx < "/sys/class/net/$iface/statistics/tx_bytes"

        if [ "$prev_time" -gt 0 ] && [ "$now" -gt "$prev_time" ]; then
            dt=$((now - prev_time))
            dbits=$(((rx - prev_rx) * 8))
            ubits=$(((tx - prev_tx) * 8))
            dtenths=$((dbits / dt / 100000))
            utenths=$((ubits / dt / 100000))
            line="$(printf '%%{F%s}%d.%d%%{F-}/%%{F%s}%d.%d%%{F-}' \
                "$DOWN_COLOR" "$((dtenths / 10))" "$((dtenths % 10))" \
                "$UP_COLOR" "$((utenths / 10))" "$((utenths % 10))")"
        else
            line="$(printf '%%{F%s}0.0%%{F-}/%%{F%s}0.0%%{F-}' "$DOWN_COLOR" "$UP_COLOR")"
        fi

        prev_rx=$rx
        prev_tx=$tx
        prev_time=$now
    fi

    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
    sleep 2
done
