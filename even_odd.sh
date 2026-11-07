#! /usr/bin/env bash

#COLLECT USER INPUT
read -p "Enter an Integer: " user_input


#PERFORM OPERATION
result=$((user_input%2))

#CHECK IF OUTPUT "result" IS EVEN OR ODD
if [[ $result == 0 ]]; then
    echo "Number is Even"
else
    echo "Number is Odd"
fi

