#!/bin/bash
# start/stop are allowed without a password by
# /etc/polkit-1/rules.d/50-mohammad-dev-services.rules
if systemctl is-active --quiet docker; then
    systemctl stop docker docker.socket containerd
    notify-send "Docker" "Stopped"
else
    systemctl start docker
    notify-send "Docker" "Started"
fi
