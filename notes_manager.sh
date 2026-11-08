#!/usr/bin/env bash
# notes_manager.sh - a simple script for adding notes to notes.txt

# File where all notes are stored
notes_file="notes.txt"

# Keep looping until the user says they're done
while true; do
    # Ask the user whether they want to add a note (-p shows a prompt, -r keeps backslashes as typed)
    read -r -p "Do you want to add a new note? (y/n) " user_input

    if [[ "$user_input" == "y" || "$user_input" == "Y" ]]; then
        # Ask for the note itself
        read -r -p "Enter your note: " note

        # Append (>>) the note so earlier notes are not overwritten
        echo "$note" >> "$notes_file"
        echo "Note saved."

        # Show every note saved so far
        cat "$notes_file"

    # The user is finished adding notes
    elif [[ "$user_input" == "n" || "$user_input" == "N" ]]; then
        echo "Goodbye!"
        # Exit the while loop, which ends the script
        break

    # Anything other than y/Y/n/N is rejected, and the loop asks again
    else
        echo "Enter a valid input"
    fi
done
