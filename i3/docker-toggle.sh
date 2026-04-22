#!/bin/bash
if systemctl is-active --quiet docker; then
    sudo systemctl stop docker docker.socket containerd
    notify-send "Docker" "Stopped"
else
    sudo systemctl start docker
    notify-send "Docker" "Started"
fi
