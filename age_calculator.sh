#!/usr/bin/env bash

#COLLECTING USER INPUT
read -p "Enter your birth year: " age
read -p "Enter the current year: " year

#AGE OPERATION
result=$((year-age))

# INTERPRETATION
echo "Your age is $result"
