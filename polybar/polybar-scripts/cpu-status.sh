#!/bin/bash

read_cpu() {
    read -r _ u n s idle iowait irq softirq steal _ < /proc/stat
    idle_all=$((idle + iowait))
    total=$((u + n + s + idle + iowait + irq + softirq + steal))
}

read_cpu
prev_total=$total
prev_idle=$idle_all
last=""

while true; do
    sleep 2
    read_cpu
    dt=$((total - prev_total))
    di=$((idle_all - prev_idle))
    prev_total=$total
    prev_idle=$idle_all
    if [ "$dt" -gt 0 ]; then
        line="$(printf '%s%%' "$((100 * (dt - di) / dt))")"
    else
        line="0%"
    fi
    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
done
