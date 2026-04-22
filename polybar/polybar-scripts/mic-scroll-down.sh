#!/bin/bash
vol=$(pactl get-source-volume @DEFAULT_SOURCE@ | grep -oP '\d+(?=%)' | head -1)
[ "$vol" -gt 5 ] && pactl set-source-volume @DEFAULT_SOURCE@ -5% || pactl set-source-volume @DEFAULT_SOURCE@ 0%
