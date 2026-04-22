#!/bin/bash
uptime -p | sed -e 's/up //g' -e 's/ weeks\?,/w/g' -e 's/ days\?,/d/g' -e 's/ hours\?.*$/h/g'
