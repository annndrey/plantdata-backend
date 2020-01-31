#define TEST true   //Set TRUE for testing

#include <ArduinoJson.h>

#include <EEPROM.h>

#include <DallasTemperature.h>
#include <OneWire.h>
#include <Adafruit_BMP280.h>
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

#define ONE_WIRE_BUS D3 //pin for Dallas temperature sensors
#define DHTPIN0 D21
#define DHTTYPE0 DHT22
#define DHTPIN1 3
#define DHTTYPE1 DHT22
#define CO2_0  ADC2
#define WEIGHT_SENSORS_AMOUNT 0

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

Adafruit_BMP280 bmp; 
DHT dht0(DHTPIN0, DHTTYPE0);
DHT dht1(DHTPIN1, DHTTYPE0);
HX711 scale[WEIGHT_SENSORS_AMOUNT];
int scale_factor = 911100;
OneWire oneWire(ONE_WIRE_BUS);// Setup a oneWire instance to communicate with a OneWire device
DallasTemperature tempSensors(&oneWire);// Pass our oneWire reference to Dallas Temperature sensor 
DeviceAddress sensor0 = {0x28, 0x62, 0xDA, 0x05, 0x00, 0x00, 0x00, 0xD1};

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
  //OTA update handler section
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
  
  //Sensors init section
  tempSensors.begin();
  
  pinMode(DHTPIN0, INPUT);
  Wire.begin();
  dht0.begin();  //  запуск датчика DHT
  
  dht1.begin();
  TSL2561.init();
  Serial.println("Light ready!");

  //BMP280 init section
  if (!bmp.begin()) {
    Serial.println(F("Could not find a valid BMP280 sensor, check wiring!"));
    while (1);
  }

  // Default settings from datasheet. 
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,     // Operating Mode
                  Adafruit_BMP280::SAMPLING_X2,     // Temp. oversampling 
                  Adafruit_BMP280::SAMPLING_X16,    // Pressure oversampling 
                  Adafruit_BMP280::FILTER_X16,      // Filtering
                  Adafruit_BMP280::STANDBY_MS_500); // Standby time

  //Scales init section
  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scale[i].begin(LOADCELL_DOUT_PIN[i], LOADCELL_SCK_PIN[i], 64);
    scale[i].set_scale();
    scale[i].set_offset();
    Serial.println("WGHT ready");
  }

  //webserver init section
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
  int c0 = analogRead(CO2_0); //reading CO2 sensor values
  c0 = map(c0, 0, 4095, 0, 1023); //because ESP32 has 12-bit ADC
  
  float h0 = dht0.readHumidity();   // reading humidity
  float t0 = dht0.readTemperature();  // reading temperature from humidity sensor
  
  float p0 = bmp.readPressure();   // reading pressure from BMP280
  float t1 = bmp.readTemperature();  // reading temperature from BMP280

  tempSensors.requestTemperatures(); // Send the command to get temperatures from Dallas temp sensors
  float t2 = tempSensors.getTempC(sensor0);
  
  unsigned long l0 = TSL2561.readVisibleLux();
  
  /*Reading temperature sensor
  int tmpA = analogRead(ADC1);
  float Rt0 = 4095.0 / tmpA - 1.0; //using 4095, because ESP32 has 12-bit ADC
  Rt0 = R0 * Rt0;
  float tempA = 1.0 / (log(Rt0 / R0) / B + 1 / 298.15) - 273.15;
  */
  
  double scalevalue[WEIGHT_SENSORS_AMOUNT];
  for (int i = 0; i < WEIGHT_SENSORS_AMOUNT; i++)
  {
    scalevalue[i] = scale[i].get_value(10);
  }

  const int json_capacity = JSON_ARRAY_SIZE(10) + 10*JSON_OBJECT_SIZE(3);
  StaticJsonDocument<json_capacity> info;
  info["UUID"] = String(WiFi.macAddress());
  JsonArray pdata = info.createNestedArray("data");
  
  JsonObject probe0 = pdata.createNestedObject();
  probe0["ptype"] = "temp";
  probe0["label"] = "T0";
  probe0["value"] = t0;

  JsonObject probe1 = pdata.createNestedObject();
  probe1["ptype"] = "temp";
  probe1["label"] = "T1";
  probe1["value"] = t1;

  JsonObject probe2 = pdata.createNestedObject();
  probe2["ptype"] = "temp";
  probe2["label"] = "T2";
  probe2["value"] = t2;

  JsonObject probe3 = pdata.createNestedObject();
  probe3["ptype"] = "humid";
  probe3["label"] = "H0";
  probe3["value"] = h0;
  /*
  JsonObject probe4 = pdata.createNestedObject();
  probe4["ptype"] = "humid";
  probe4["label"] = "H1";
  probe4["value"] = -1;
  */
  JsonObject probe5 = pdata.createNestedObject();
  probe5["ptype"] = "pres";
  probe5["label"] = "P0";
  probe5["value"] = p0;

  JsonObject probe6 = pdata.createNestedObject();
  probe6["ptype"] = "co2";
  probe6["label"] = "C0";
  probe6["value"] = c0;
  /*
  JsonObject probe7 = pdata.createNestedObject();
  probe7["ptype"] = "co2";
  probe7["label"] = "C1";
  probe7["value"] = -1;
  */
  JsonObject probe8 = pdata.createNestedObject();
  probe8["ptype"] = "light";
  probe8["label"] = "L0";
  probe8["value"] = l0;
  
  String sensorData;
  serializeJson(info, sensorData);
  return sensorData;
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
  const int json_capacity = JSON_ARRAY_SIZE(10) + 10*JSON_OBJECT_SIZE(3);
  StaticJsonDocument<json_capacity> info;
  info["UUID"] = String(WiFi.macAddress());
  JsonArray pdata = info.createNestedArray("data");
  
  JsonObject probe0 = pdata.createNestedObject();
  probe0["ptype"] = "temp";
  probe0["label"] = "T0";
  probe0["value"] = -1;

  JsonObject probe1 = pdata.createNestedObject();
  probe1["ptype"] = "temp";
  probe1["label"] = "T1";
  probe1["value"] = -1;

  JsonObject probe2 = pdata.createNestedObject();
  probe2["ptype"] = "temp";
  probe2["label"] = "T2";
  probe2["value"] = -1;

  JsonObject probe3 = pdata.createNestedObject();
  probe3["ptype"] = "humid";
  probe3["label"] = "H0";
  probe3["value"] = -1;

  JsonObject probe4 = pdata.createNestedObject();
  probe4["ptype"] = "humid";
  probe4["label"] = "H1";
  probe4["value"] = -1;

  JsonObject probe5 = pdata.createNestedObject();
  probe5["ptype"] = "pres";
  probe5["label"] = "P0";
  probe5["value"] = -1;

  JsonObject probe6 = pdata.createNestedObject();
  probe6["ptype"] = "co2";
  probe6["label"] = "C0";
  probe6["value"] = -1;

  JsonObject probe7 = pdata.createNestedObject();
  probe7["ptype"] = "co2";
  probe7["label"] = "C1";
  probe7["value"] = -1;

  JsonObject probe8 = pdata.createNestedObject();
  probe8["ptype"] = "light";
  probe8["label"] = "L0";
  probe8["value"] = -1;
  
  String sensorData;
  serializeJson(info, sensorData);
  return sensorData;
}
