#/bin/bash
NUM_DISPLAYS=$(xrandr --query | grep -i " connected" | wc -l)

echo "RUNNING"
if [ $NUM_DISPLAYS -eq 3 ];
    then
        # Enable 3 screens
        # Laptop on the left, 2 external monitors on the right
        xrandr --output eDP --primary --mode 1920x1080 --pos 0x0 --rotate normal --output HDMI-A-0 --mode 1920x1080 --pos 3840x0 --rotate normal --output DisplayPort-0 --mode 1920x1080 --pos 1920x0 --rotate normal
        # Laptop on the right, 2 external monitors on the left
       # xrandr --output eDP --primary --mode 1920x1080 --pos 0x0 --rotate normal --output HDMI-A-0 --mode 2560x1440 --pos 4480x0 --rotate normal --output DisplayPort-0 --mode 2560x1440 --pos 1920x0 --rotate normal
    else
        # Enable one screen (laptop display)
        xrandr --output eDP --primary --mode 1920x1080 --pos 0x0 --rotate normal --output HDMI-A-0 --off --output DisplayPort-0 --off
fi
