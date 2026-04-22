#!/bin/bash

DEVICE="AC:BF:71:83:51:BA"
bt=$(printf '\uf294')
blue="#7aa2f7"
disabled="#414868"

connected=$(bluetoothctl info "$DEVICE" 2>/dev/null | grep "Connected: yes")

if [ -n "$connected" ]; then
    echo "%{F${blue}}${bt} Zyfer%{F-}"
else
    echo "%{F${disabled}}${bt} Off%{F-}"
fi
