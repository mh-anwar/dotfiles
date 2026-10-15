#!/usr/bin/env bash
# Pick an audio output or microphone.  Sets the default, moves anything that's
# currently playing/recording to it, and confirms with a notification.
#   audio-switch.sh            rofi menu (outputs + inputs)
#   audio-switch.sh list       print "kind<TAB>name<TAB>description<TAB>*" rows
#   audio-switch.sh set KIND NAME

rows_for() { # pactl-type kind default
    pactl -f json list "$1" | python3 -c '
import json, sys
kind, default = sys.argv[1], sys.argv[2]
for s in json.load(sys.stdin):
    # The EasyEffects virtual devices sit in front of the real ones; never pick them.
    if s["name"].endswith(".monitor") or s["name"].startswith("easyeffects_"):
        continue
    mark = "*" if s["name"] == default else ""
    print("\t".join((kind, s["name"], s["description"], mark)))' "$2" "$3"
}

list() {
    rows_for sinks output "$(pactl get-default-sink)"
    rows_for sources input "$(pactl get-default-source)"
}

set_device() {
    local kind=$1 name=$2 desc
    if [[ $kind == output ]]; then
        pactl set-default-sink "$name"
        for i in $(pactl list short sink-inputs | cut -f1); do pactl move-sink-input "$i" "$name" 2>/dev/null; done
        desc=$(pactl -f json list sinks | python3 -c 'import json,sys; print(next(s["description"] for s in json.load(sys.stdin) if s["name"]==sys.argv[1]))' "$name")
        # Speaker EQ only makes sense on the laptop speakers.
        if pgrep -x easyeffects >/dev/null; then
            [[ $name == *Speaker* ]] && easyeffects -l "Laptop speakers" || easyeffects -l "Headphones"
        fi
        notify-send -a osd -i audio-speakers -h string:x-canonical-private-synchronous:audio-dev "Output" "$desc"
    else
        pactl set-default-source "$name"
        for i in $(pactl list short source-outputs | cut -f1); do pactl move-source-output "$i" "$name" 2>/dev/null; done
        desc=$(pactl -f json list sources | python3 -c 'import json,sys; print(next(s["description"] for s in json.load(sys.stdin) if s["name"]==sys.argv[1]))' "$name")
        notify-send -a osd -i audio-input-microphone -h string:x-canonical-private-synchronous:audio-dev "Microphone" "$desc"
    fi
}

case "${1:-}" in
    list) list; exit ;;
    set)  set_device "$2" "$3"; exit ;;
esac

rows=$(list)
menu=$(while IFS=$'\t' read -r kind name desc cur; do
    icon=$([[ $kind == output ]] && echo "🔊" || echo "🎤")
    mark=$([[ -n $cur ]] && echo "  ✓" || echo "")
    printf '%s  %s%s\n' "$icon" "$desc" "$mark"
done <<< "$rows")

idx=$(rofi -dmenu -i -p "Audio" -format i -no-custom <<< "$menu") || exit 0
line=$(sed -n "$((idx + 1))p" <<< "$rows")
IFS=$'\t' read -r kind name _ _ <<< "$line"
set_device "$kind" "$name"
