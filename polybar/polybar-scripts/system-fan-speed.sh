#https://github.com/polybar/polybar-scripts/tree/master/polybar-scripts/system-fan-speed
#!/bin/sh

speed=$(sensors | grep Processor | awk '{print $3; exit}')
echo $speed
if [ "$speed" != "" ]; then
    speed_round=$(echo "$speed/1000" | bc -l | LANG=C xargs printf "%.1f\n")
    echo "# $speed_round"
else
   echo "#"
fi
