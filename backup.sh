#!/usr/bin/env bash
# backup.sh - makes a timestamped copy of a file and saves it in Bash Scripts.

# Ask for the folder the file is in (use the full path, e.g. /home/dak_trader/Documents)
read -p "Enter a file path: " file_path

# Ask for the name of the file to back up
read -p "Enter a file name: " file_name

# Current date and time, e.g. 2026-11-08_22-07-00, used to make each backup name unique
timestamp=$(date +"%Y-%m-%d_%H-%M-%S")

# Go into the folder; if it doesn't exist, show an error and stop the script
cd "$file_path" || { echo "Directory not found"; exit 1; }

# Check that the file exists in that folder (-f = is a regular file)
if [[ -f $file_name ]]; then
    # Copy it to Bash Scripts as <name>_<timestamp>
    cp "$file_name" "/home/dak_trader/Bash Scripts/${file_name}_$timestamp"
    echo "Backup Successful"

else
    # The file isn't in the folder you entered
    echo "File not found"
fi
