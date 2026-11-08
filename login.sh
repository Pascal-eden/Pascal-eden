#! /usr/bin/env bash
# login.sh - A simple login prompt that checks a username and password
# against values stored in this script.

# The correct credentials the user must enter to log in.
passwd=dak_trader99
username=Dak_Trader


# Ask the user for their username.
# -p shows a prompt message before reading input.
read -p "Enter your username: " set_username

# Ask the user for their password.
# -s (silent) hides what is typed so the password isn't shown on screen.
read -sp "Enter your Password: " set_passwd


# Check that BOTH the username and password match the stored values.
# [[ ... ]] is Bash's test command; && means both conditions must be true.
if [[ $username == $set_username  && $set_passwd == $passwd ]]; then
    # Both matched: let the user in.
    echo "Login successful!"
else
    # At least one didn't match: reject the login.
    echo "Invalid username or password."
fi
