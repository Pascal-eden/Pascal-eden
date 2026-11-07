#! /usr/bin/env bash
# Prints the multiplication table (1 to 12) for a number entered by the user.

# Ask the user for a number
read -p "Enter a number: " user_input

# Accept only non-negative integers (one or more digits)
if ! [[ $user_input =~ ^[0-9]+$ ]]; then
    # Not a number: show an error and stop
    echo "Please enter a valid number."
else
    # Print the table from 1 to 12
    for i in {1..12}; do
        # Multiply the input by the current step
        result=$(( user_input * i ))

        # Show the line, e.g. "5 * 3 = 15"
        echo "$user_input * $i = $result"
    done
fi
