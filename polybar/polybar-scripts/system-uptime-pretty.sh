#https://github.com/polybar/polybar-scripts/tree/master/polybar-scripts/system-uptime-pretty

#!/bin/sh

uptime --pretty | sed 's/up //' | sed 's/\ years\?,/y/' | sed 's/\ weeks\?,/w/' | sed 's/\ days\?,/d/' | sed 's/\ hours\?,\?/h/' | sed 's/\ minutes\?/m/'
