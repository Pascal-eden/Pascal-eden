#!/usr/bin/env bash

#WELCOME MESSAGE
echo "Hello, welcome to my calculator"

#COLLECT FIRST NUMBER
echo "What is the first number?"
read first_number

#COLLECT SECOND NUMBER
echo "What is the second number?"
read second_number


#ADDITION OPERATOR
addition=$((first_number+second_number))
echo "Addition: $addition"

#SUBTRACTION OPERATOR
minus=$((first_number-second_number))
echo "Subtraction: $minus"

#MULTIPLICATION OPERATOR
Multiplication=$((first_number*second_number))
echo "Multiplication: $Multiplication"

#DIVISION OPERATOR
DIVISION=$((first_number/second_number))
echo "DIVISION: $DIVISION"