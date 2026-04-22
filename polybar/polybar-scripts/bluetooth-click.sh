#!/bin/bash

DEVICE="AC:BF:71:83:51:BA"

if bluetoothctl info "$DEVICE" 2>/dev/null | grep -q "Connected: yes"; then
    bluetoothctl disconnect "$DEVICE" &>/dev/null &
else
    bluetoothctl power on &>/dev/null
    sleep 0.5
    bluetoothctl connect "$DEVICE" &>/dev/null &
fi
