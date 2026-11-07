#! /usr/bin/env bash

#COLLECTS USER INPUT 
read -p "Enter temperature in Celsius:" temp_celsius

#TEMPERATURE OPERATION
result=$(echo "($temp_celsius*9/5)+32"|bc -l)


#OUTPUT
echo "Temperature in Fahrenheit: $(printf "%.2f\n" "$result")"

# $(printf "%.2f\n" "$result") converts the output from variable 'result' to 2 d.p
# bc -l is used when working with decimal for other operations bc is fine







