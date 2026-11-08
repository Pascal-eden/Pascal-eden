#! /usr/bin/env bash
# Number Guessing Game
# The script picks a random number between 1 and 10 and keeps asking
# the user to guess until they get it right, giving hints along the way.

# Generate a random number from 1 to 10
# ($RANDOM gives 0-32767; % 10 makes it 0-9, then + 1 makes it 1-10)
number=$((RANDOM % 10 + 1))

# Loop until the user guesses correctly
while true; do
    # Prompt for a guess (-r keeps backslashes as typed, -p shows the prompt)
    read -rp "Enter a number (1-10): " user_input

    # Check that the input contains only digits; if not, ask again
    if ! [[ $user_input =~ ^[0-9]+$ ]]; then
        echo "Please enter a valid number."
        continue
    fi

    # Compare the guess with the secret number and give a hint
    if (( user_input > number )); then
        echo "Too high!"
    elif (( user_input < number )); then
        echo "Too low!"
    else
        # Correct guess: congratulate the user and exit the loop
        echo "Correct!"
        break
    fi
done
