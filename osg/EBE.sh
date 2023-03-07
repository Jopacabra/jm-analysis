#!/bin/bash
# EBE.sh: a single event
printf "Start time: "; /bin/date
printf "Job is running on node: "; /bin/hostname
printf "Job running as user: "; /usr/bin/id
printf "Job is running in directory: "; /bin/pwd
echo
echo "Working hard..."
# Activate the python virtual environment
export PATH=/usr/bin:$PATH
source /usr/jma/bin/activate
# Change directory to the project root
cd /usr/jm-analysis || exit
# Pull any changes from the git
# git pull
# Test osu-hydro and trento
echo "Testing osu-hydro and trento..."
trento --help
osu-hydro --help
# Run the script
# python3 EBE.py
echo "Testing complete!"