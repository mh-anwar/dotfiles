#!/bin/bash

mic_on=$'\uf130'
mic_off=$'\uf131'
blue="#7aa2f7"
disabled="#414868"

output() {
    muted=$(pactl get-source-mute @DEFAULT_SOURCE@ | awk '{print $2}')
    vol=$(pactl get-source-volume @DEFAULT_SOURCE@ | grep -oP '\d+%' | head -1)

    if [ "$muted" = "yes" ]; then
        echo "%{F${disabled}}${mic_off}%{F-}"
    else
        echo "%{F${blue}}${mic_on}%{F-} ${vol}"
    fi
}

output

pactl subscribe | while read -r event; do
    if echo "$event" | grep -q "source"; then
        output
    fi
done
