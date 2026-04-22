#!/bin/bash
vol=$(pactl get-source-volume @DEFAULT_SOURCE@ | grep -oP '\d+(?=%)' | head -1)
[ "$vol" -lt 149 ] && pactl set-source-volume @DEFAULT_SOURCE@ +5% || pactl set-source-volume @DEFAULT_SOURCE@ 153%
