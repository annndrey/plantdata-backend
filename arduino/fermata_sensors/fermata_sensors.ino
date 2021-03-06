#include <Wire.h>
#include <DHT.h>
#include <HX711.h>
#include <Digital_Light_TSL2561.h>
#define DHTPIN0 2
#define DHTTYPE0 DHT22
#define DHTPIN1 3
#define DHTTYPE1 DHT22
#define PIN_MQ135  A5
#define WEIGHT_SENSORS_AMOUNT 5

int sensorValue;
int wght;
int moist;
int tmpA;
float tempA;

float bar_pressure;
float bar_temp;

//load cell section
const int LOADCELL_DOUT_PIN[WEIGHT_SENSORS_AMOUNT] = {5, 7, 9, 11, 13};
const int LOADCELL_SCK_PIN[WEIGHT_SENSORS_AMOUNT] = {4, 6, 8, 10, 12};
float calibration_factor = 452;
long offset = 0;
float scaleunits;
double scalevalue[WEIGHT_SENSORS_AMOUNT];

//load cell section

int a1pin = A1;
int a2pin = A2;
int a3pin = A3;
int d3pin = 3;

int uv;
unsigned long lght;

const int B = 4275;
const int R0 = 100000; //B value of the thermistor

DHT dht0(DHTPIN0, DHTTYPE0);
DHT dht1(DHTPIN1, DHTTYPE0);
HX711 scale[WEIGHT_SENSORS_AMOUNT];
int scale_factor = 911100;

void setup()
{
  Wire.begin();
  Serial.begin(9600);   // запуск передачи данных
  //Serial.println("Begin init...");
  //Wire.begin();
  //Serial.println("Wire Initialization completed");
  //Serial.println("Serial Initialization completed");
  dht0.begin();  //  запуск датчика DHT
  //Serial.println("DHT0 Initialization completed");
  dht1.begin();
  TSL2561.init();
  //Serial.println("DHT1 Initialization completed");
  //Serial.println("Barometer Initialization completed");
  //Initialazing weight sensors
  for(int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scale[i].begin(LOADCELL_DOUT_PIN[i], LOADCELL_SCK_PIN[i], 64);
    scale[i].set_scale();
    scale[i].set_offset();
  }
  //Code added by Dan 18/9/2019
  //offset = scale.get_offset();
  //offset = offset - (50*calibration_factor); //substract 50 gramm weight from offset
  //scale.set_offset(offset);
  //scale.begin(A1, A0);
  //scale.set_scale(-15920);
  //scale.set_scale();
  //scale.tare();
}

void loop()
{
  // добавляем паузы в  секунды между измерениями
  delay(3000);

  sensorValue = analogRead(0);
  //wght = analogRead(2);
  float h0 = dht0.readHumidity();   // считывание влажности
  float t0 = dht0.readTemperature();  // считывание температуры
  float h1 = dht1.readHumidity();   // считывание влажности
  float t1 = dht1.readTemperature();  // считывание температуры
  bar_pressure = 0;//barometer.readPressureMillibars();
  bar_temp = 0;//barometer.readTemperatureC();

  lght = TSL2561.readVisibleLux();
  tmpA = analogRead(a1pin);
  float Rt0 = 1023.0 / tmpA - 1.0;
  Rt0 = R0 * Rt0;
  tempA = 1.0 / (log(Rt0 / R0) / B + 1 / 298.15) - 273.15;
  // UV Sensor
  int uvsingle;
  // http://wiki.seeedstudio.com/Grove-UV_Sensor/
  long  uvsum = 0;
  for (int i = 0; i < 1024; i++) // accumulate readings for 1024 times
  {
    uvsingle = analogRead(a3pin);
    uvsum = uvsingle + uvsum;
    delay(2);
  }
  long uvmean = uvsum / 1024;
  uv = (uvmean * 1000 / 4.3 - 83) / 21;
  uv = -1;

  //
  for(int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scalevalue[i] = scale[i].get_value(10);
  }
  
  //Data sending section
  
  Serial.print("{");
  for(int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    Serial.print("'WGHT");
    Serial.print(i);
    Serial.print("' : ");
    Serial.print(scalevalue[i]);
    Serial.print(", ");
  }
  Serial.print("'T0' : ");
  Serial.print(t0);
  Serial.print(", ");
  Serial.print("'H0': ");
  Serial.print(h0);
  Serial.print(", ");
  Serial.print("'T1' : ");
  Serial.print(t1);
  Serial.print(", ");
  Serial.print("'H1': ");
  Serial.print(h1);
  Serial.print(", ");
  Serial.print("'M': ");
  Serial.print(moist);
  Serial.print(", ");
  Serial.print("'TA': ");
  Serial.print(tempA);
  Serial.print(", ");
  Serial.print("'L': ");
  Serial.print(lght);
  Serial.print(", ");
  //Serial.print("'Wght': ");
  //Serial.print(wght);
  Serial.print(", ");
  Serial.print("CO2: ");
  Serial.print(sensorValue);
  Serial.print(", ");
  Serial.print("'UV': ");
  Serial.print(uv);
  //Serial.print("'Barsensor_Tmp': ");
  //Serial.print(bar_temp);
  //Serial.print(", ");
  //Serial.print("'Barsensor_Prs': ");
  //Serial.print(bar_pressure);
  Serial.print(", ");
  Serial.println("}");
}
