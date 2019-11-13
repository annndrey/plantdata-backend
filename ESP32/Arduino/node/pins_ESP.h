/*
This file redefines pins on ESP32-DEVKI1 for easier use.
There is a pin schematic
            EN|-------------------------|D13
    (ADC4) D35|-------------------------|D12
    (ADC3) D24|-------------------------|D11
    (ADC2) D23|-------------------------|D10
    (ADC1) D22|-------------------------|D9
           D21|-------------------------|D8
           D20|-------------------------|D7
           D19|-------------------------|D6
           D18|-------------------------|D5
           D17|-------------------------|D4
           D16|-------------------------|D3
           D15|-------------------------|D2
           D14|-------------------------|D1
           GND|-------------------------|GND
           VIN|-------------------------|VDD 3V3


*/


#define D1 15
#define D2 2
#define D3 4
#define D4 16
#define D5 17
#define D6 5
#define D7 18
#define D8 19
#define D9 21
#define D10 3
#define D11 1
#define D12 22
#define D13 23
#define D14 13
#define D15 12
#define D16 14
#define D17 27
#define D18 26
#define D19 25
#define D20 33
#define D21 32
#define D22 35
#define D23 34
#define D24 39
#define D25 36

#define ADC1 35
#define ADC2 34
#define ADC3 39
#define ADC4 36
