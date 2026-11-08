#!/usr/bin/env bash
# file_creator.sh - Ask the user for a file name and create it,
# unless a file with that name already exists.

# Prompt the user and store their answer in the variable "file_name"
read -p "Enter file name: " file_name

# -e checks whether anything (file or directory) exists at that path.
# The variable is quoted so names containing spaces work correctly.
if [[ -e "$file_name" ]]; then
    # Something already exists there, so don't touch it
    echo "File already exists!"
else
    # touch creates a new, empty file
    touch "$file_name"
    echo "File created successfully!"
fi
