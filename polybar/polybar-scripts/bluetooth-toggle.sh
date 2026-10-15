#!/bin/bash

DEVICE="AC:BF:71:83:51:BA"
DEV_PATH="/org/bluez/hci0/dev_AC_BF_71_83_51_BA"
bt=$'\uf025'
blue="#8ab4f8"
disabled="#52525b"

output() {
    if bluetoothctl info "$DEVICE" 2>/dev/null | grep -q "Connected: yes"; then
        echo "%{F${blue}}${bt} Zyfer%{F-}"
    else
        echo "%{F${disabled}}${bt} Off%{F-}"
    fi
}

output

dbus-monitor --system \
    "type='signal',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',path='${DEV_PATH}'" 2>/dev/null |
while read -r line; do
    case "$line" in
        *Connected*) output ;;
    esac
done
