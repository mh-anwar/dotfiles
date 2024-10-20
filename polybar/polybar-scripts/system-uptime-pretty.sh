#https://github.com/polybar/polybar-scripts/tree/master/polybar-scripts/system-uptime-pretty

#!/bin/sh

uptime --pretty | sed -E 's/up //; s/([0-9]+) years?/, &y/; s/([0-9]+) weeks?/, &w/; s/([0-9]+) days?/, &d/; s/([0-9]+) hours?/, &h/; s/, [0-9]+ minutes?//g; s/,/ /g; s/ hours?//g; s/ days?//g; s/^[ ,]+//; s/[ ,]+$//; s/[ ,]+/ /g'
#| sed 's/\ minutes\?/m/'
