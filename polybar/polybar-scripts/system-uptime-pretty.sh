#https://github.com/polybar/polybar-scripts/tree/master/polybar-scripts/system-uptime-pretty

#!/bin/sh

# uptime --pretty | sed -E 's/up //; s/([0-9]+) years?/, &y/; s/([0-9]+) weeks?/, &w/; s/([0-9]+) days?/, &d/; s/([0-9]+) hours?/, &h/; s/, [0-9]+ minutes?//g; s/,/ /g; s/ hours?//g; s/ days?//g; s/^[ ,]+//; s/[ ,]+$//; s/[ ,]+/ /g'
#| sed 's/\ minutes\?/m/'


# Get the uptime information
uptime_output=$(uptime -p)

# Parse the uptime into simplified format
simplified_uptime=$(echo "$uptime_output" | awk '
{
    # Remove "up" from the output
    sub("up ", "")

    # Replace "weeks", "days", "hours", "minutes" with w, d, h, m
    gsub("weeks?", "w")
    gsub("days?", "d")
    gsub("hours?", "h")
    gsub("minutes?", "m")

    # Split on commas and trim whitespace
    n = split($0, arr, ",")
    result = ""
    for (i = 1; i <= n; i++) {
        gsub(/^ +| +$/, "", arr[i])
        result = result (result ? " " : "") arr[i]
    }

    print result
}')

# Output the simplified uptime
echo "$simplified_uptime"
