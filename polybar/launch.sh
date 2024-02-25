# Terminate already running bar instances
killall -q polybar

# https://github.com/polybar/polybar/issues/763
if type "xrandr"; then
  for m in $(xrandr --query | grep " connected" | cut -d" " -f1); do
    MONITOR=$m polybar --reload the_one_bar &
  done
else
  polybar --reload the_one_bar &
fi

# echo "Polybar launched..."
