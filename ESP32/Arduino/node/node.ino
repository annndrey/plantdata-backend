#define TEST 1

#include <ArduinoJson.h>

#include <EEPROM.h>

#include <Digital_Light_ISL29035.h>
#include <Digital_Light_TSL2561.h>
#include <DHT.h>
#include <DHT_U.h>
#include <Wire.h>
#include <ssl_client.h>
#include <WiFiClientSecure.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HX711.h>
#include "pins_ESP.h"

#define DHTPIN0 D21
#define DHTTYPE0 DHT22
#define DHTPIN1 3
#define DHTTYPE1 DHT22
#define PIN_MQ135  ADC2
#define WEIGHT_SENSORS_AMOUNT 2

IPAddress local_ip(192, 168, 1, 140);
IPAddress gateway(192, 168, 0, 254);
IPAddress subnet(255, 255, 255, 0);


const char* ssid = "aladdin";  // Enter SSID here
const char* password = "Glin@2913";  //Enter Password here

const char* host = "espinit"; //mDNS host name

WebServer server(80);


int tmpA = 0;
float tempA;

//load cell section
const int LOADCELL_DOUT_PIN[6] = {D16, D17, D18, D19, D20, D21};
const int LOADCELL_SCK_PIN[6] = {D3, D4, D5, D6, D7, D8};

const int B = 4275;
const int R0 = 100000; //B value of the thermistor

DHT dht0(DHTPIN0, DHTTYPE0);
DHT dht1(DHTPIN1, DHTTYPE0);
HX711 scale[WEIGHT_SENSORS_AMOUNT];
int scale_factor = 911100;

void setup()
{
  Serial.begin(115200);
  Serial.println("Connecting to ");
  Serial.println(ssid);
  WiFi.mode(WIFI_AP_STA);
  WiFi.config(local_ip, gateway, subnet);
  WiFi.begin(ssid, password);
  //check wi-fi is connected to wi-fi network
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected..!");
  Serial.print("Got IP: ");
  Serial.println(WiFi.localIP());
  //OTA check section
  MDNS.begin(host);
  //OTA update handler
  server.on("/update", HTTP_POST, []() {
    server.sendHeader("Connection", "close");
    server.send(200, "text/plain", (Update.hasError()) ? "FAIL" : "OK");
    ESP.restart();
  }, []() {
    HTTPUpload& upload = server.upload();
    if (upload.status == UPLOAD_FILE_START) {
      Serial.setDebugOutput(true);
      Serial.printf("Update: %s\n", upload.filename.c_str());
      if (!Update.begin()) { //start with max available size
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true)) { //true to set the size to the current progress
        Serial.printf("Update Success: %u\nRebooting...\n", upload.totalSize);
      } else {
        Update.printError(Serial);
      }
      Serial.setDebugOutput(false);
    } else {
      Serial.printf("Update Failed Unexpectedly (likely broken connection): status=%d\n", upload.status);
    }
  });
  //
  pinMode(DHTPIN0, INPUT);
  Wire.begin();
  dht0.begin();  //  запуск датчика DHT
  Serial.println("DHT0 ready");
  dht1.begin();
  TSL2561.init();
  Serial.println("Light ready!");

  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scale[i].begin(LOADCELL_DOUT_PIN[i], LOADCELL_SCK_PIN[i], 64);
    scale[i].set_scale();
    scale[i].set_offset();
    Serial.println("WGHT ready");
  }

  server.on("/sensor_data", handle_SendSensorData);
  server.on("/info", handle_SendInfo);
  server.begin();
  MDNS.addService("http", "tcp", 80);
  Serial.printf("Ready! Open http://%s.local in your browser\n", host);
  Serial.println("Setup complet");
}

void loop()
{
  server.handleClient();
  delay(1);

  //Attempt to reconnect in case of lousing connection
  while ( WiFi.status() != WL_CONNECTED) {
    Serial.print("Attempting to connect to SSID: ");
    Serial.println(ssid);
    WiFi.begin(ssid, password);
    // wait 10 seconds for connection:
    delay(10000);
  }
}



void handle_SendSensorData() {
  #if TEST
  server.send(200, "application/json", Test());
  #else
  server.send(200, "application/json", ReadSensors());
  #endif
}

void handle_SendInfo() {
  server.send(200, "application/json", SendInfo());
}


String ReadSensors()  {
  Serial.println("Reading Sensors!");
  int sensorCO2Value = analogRead(PIN_MQ135);
  sensorCO2Value = map(sensorCO2Value, 0, 4095, 0, 1023); //because ESP32 has 12-bit ADC
  float h0 = dht0.readHumidity();   // считывание влажности
  float t0 = dht0.readTemperature();  // считывание температуры
  float h1 = -1;   // считывание влажности
  float t1 = -1;  // считывание температуры
  unsigned long lght = TSL2561.readVisibleLux();
  //Reading temperature sensor
  int tmpA = analogRead(ADC1);
  float Rt0 = 4095.0 / tmpA - 1.0; //using 4095, because ESP32 has 12-bit ADC
  Rt0 = R0 * Rt0;
  float tempA = 1.0 / (log(Rt0 / R0) / B + 1 / 298.15) - 273.15;
  //
  double scalevalue[WEIGHT_SENSORS_AMOUNT];
  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scalevalue[i] = scale[i].get_value(10);
  }

  const int json_capacity = JSON_OBJECT_SIZE(8 + WEIGHT_SENSORS_AMOUNT);
  StaticJsonDocument<json_capacity> doc;
  doc["T0"] = t0;
  doc["H0"] = h0;
  doc["T1"] = t1;
  doc["H1"] = h1;
  doc["TA"] = tempA;
  doc["L"] = lght;
  doc["CO2"] = sensorCO2Value;
  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    String key = String("WGHT" + String(i));
    doc[key] = scalevalue[i];
  }
  String sensorData;
  serializeJson(doc, sensorData);
  return sensorData;
  /*
    String sensorData;
    sensorData.concat("{'T0' : ");
    sensorData.concat(t0);
    sensorData.concat(", 'H0': ");
    sensorData.concat(h0);
    sensorData.concat(", 'T1': ");
    sensorData.concat(t1);
    sensorData.concat(", 'H1': ");
    sensorData.concat(h1);
    sensorData.concat(", 'TA': ");
    sensorData.concat(tempA);
    sensorData.concat(", 'L': ");
    sensorData.concat(lght);
    sensorData.concat(", 'CO2': ");
    sensorData.concat(sensorCO2Value);
    for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
    {
    sensorData.concat(", ");
    sensorData.concat("'WGHT");
    sensorData.concat(i);
    sensorData.concat("': ");
    sensorData.concat(scalevalue[i]);
    }
    sensorData.concat("}");
    return sensorData;
  */
}

String SendInfo() {
  const int json_capacity = JSON_OBJECT_SIZE(9);
  StaticJsonDocument<json_capacity> info;
  info["IP"] = WiFi.localIP().toString();
  info["gateway"] = WiFi.gatewayIP().toString();
  info["MAC"] = String(WiFi.macAddress());
  info["subnet mask"] = WiFi.subnetMask().toString();
  info["mDNS host mask"] = host;
  String infoData;
  serializeJson(info, infoData);
  return infoData;
}

String Test() {
  const int json_capacity = JSON_OBJECT_SIZE(8 + WEIGHT_SENSORS_AMOUNT);
  StaticJsonDocument<json_capacity> doc;
  doc["T0"] = -1;
  doc["H0"] = -1;
  doc["T1"] = -1;
  doc["H1"] = -1;
  doc["TA"] = -1;
  doc["L"] = -1;
  doc["CO2"] = -1;
  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    String key = String("WGHT" + String(i));
    doc[key] = -1;
  }
  String sensorData;
  serializeJson(doc, sensorData);
  return sensorData;
}
