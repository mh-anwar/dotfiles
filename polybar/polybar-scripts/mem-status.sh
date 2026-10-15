#!/bin/bash

last=""

while true; do
    total=0
    avail=0
    while read -r key val _; do
        case "$key" in
            MemTotal:) total=$val ;;
            MemAvailable:) avail=$val ;;
        esac
    done < /proc/meminfo
    if [ "$total" -gt 0 ]; then
        line="$(printf '%d%%' "$(((total - avail) * 100 / total))")"
    else
        line="--%"
    fi
    if [ "$line" != "$last" ]; then
        printf '%s\n' "$line"
        last=$line
    fi
    sleep 3
done
