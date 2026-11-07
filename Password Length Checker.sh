#! /usr/bin/env bash

#COLLECT USER PASSWORD (-rsp is used to hide user in put and is ideal for passwd)
read -rsp "Enter your password: " user_passwd

#CONFIRMS PASSWORD STRENGTH
if [[ ${#user_passwd} -ge 8 ]]; then
    echo "Password length is acceptable"
else
    echo "Password is too short"
fi