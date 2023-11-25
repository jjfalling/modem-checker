// Device Indicator Checker

// Uses photoresistor, AS726x or TCS34725.

// This attempts to detect the status of a led (off, on, or blinking). There is a bit of fuzziness to do this and 
// you may need to adjust the values below to work with your device. Blinking with an AS726x/TCS34725 only works
// for indicators that are on/off, not alternating colors.
// It also accepts a reboot command which will open a NC relay (that triggers on high signal) for a specified amount of time to reboot the device.

// It is best if the photoresistor/color sensor is shielded from any external light sources.
// if using a photoresistor, put 10k ohm resistor between ground and the photo resistor signal


// TODO:
// - change name
// - add typing echo to serial
// - commandline seems broken on some boards (ok on a arduino micro)
// - seems string.trim() (via isspace()) may not remove newlines on some locales?
// - add option to configure via serial and persist to eeprom (drop settings option, change to set / show)
// - improve cli to be more like a normal serial interface (ie support backspace)

#include <Wire.h>
#include "Adafruit_AS726x.h"
#include "Adafruit_TCS34725.h"
#include <ArduinoSort.h>

String version = "1.1.0";

// change to match the pins used on your controller
int PhotoresistorPin = 0;  // the photoresistor and 10K pulldown are connected this pin
int RelayPin = 12;         // the power relay is connected to this pin
int ResetPin = 5;          // pin tied to reset 

// thresholds for determining the status of the device indicator. Used for both types of sensors
// good values photoresistor
int BlinkDiff = 140;         // different between high and low values to consider a indicator blinkiing
int LowerLimit = 180;        // lower reading level to consider indicator off

// good values for color sensor
// int BlinkDiff = 250;        // different between high and low values to consider a indicator blinkiing
// int LowerLimit = 10;        // lower reading level to consider indicator off

int InterCheckDelay = 150;  // how long to wait between each indicator check
int NumberOfChecks = 10;    // how many indicator checks (min is 2)

int RebootDelay = 30;          // number of sec to leave device off when rebooting
String SensorType = "photoresistor";  // sensor type to use. options are: photoresistor, as726x, tcs34725


/*****************************************************************************/

//create the color sensor object
Adafruit_AS726x ams;
//buffer to hold raw values from the color sensor
uint16_t sensorValues[AS726x_NUM_CHANNELS];
bool AS726xStarted = false;
bool TCS34725Started = false;


//Adafruit_TCS34725 tcs = Adafruit_TCS34725();
Adafruit_TCS34725 tcs = Adafruit_TCS34725(TCS34725_INTEGRATIONTIME_614MS, TCS34725_GAIN_1X);

void setup(void) {
  pinMode(ResetPin, INPUT_PULLUP);
  pinMode(RelayPin, OUTPUT);

  // attempt to start the color sensor
  if (ams.begin()) {
    AS726xStarted = true;
  }

  if (tcs.begin()) {
    TCS34725Started = true;
  }

  Serial.begin(115200);
  while (!Serial) {
    ;  // wait for serial port to connect. Only needed with a native usb port
  }
}

void indicatorStatus(bool verbose) {
  if (SensorType == "photoresistor") {
    int photocellReading;
    int photoStatus[NumberOfChecks];

    for (int i = 0; i < NumberOfChecks; i++) {
      photocellReading = analogRead(PhotoresistorPin);

      if (verbose) {
        // verbose output was requested
        Serial.print("Photoresistor Reading: ");
        Serial.println(photocellReading);
      }
      photoStatus[i] = photocellReading;
      delay(InterCheckDelay);
    }

    sortArray(photoStatus, NumberOfChecks);
    if ((photoStatus[NumberOfChecks - 1] - photoStatus[0]) > BlinkDiff) {
      // assume a difference of more than BlinkDiff between highest and lowest states means the sensor detected blinking
      Serial.println("Indicator Blinking");
    }

    else if (photoStatus[0] < LowerLimit) {
      Serial.println("Indicator Off");
    }

    else {
      Serial.println("Indicator On");
    }

  }

  else if (SensorType == "as726x") {
    if (!AS726xStarted) {
      Serial.println("ERROR: Cannot connect to AS726x sensor");
      return;
    }

    // check sensor
    int asReadings[NumberOfChecks][6];
    for (int i = 0; i < NumberOfChecks; i++) {
      ams.startMeasurement();
      bool rdy = false;
      int notReadyCount = 0;
      while (!rdy) {
        delay(5);
        rdy = ams.dataReady();
        // prevent inf loop due to sensor issues
        if (notReadyCount > 10000) {
          Serial.println("Error: AS726x sensor is not returning data");
          return;
        }
      }
      ams.readRawValues(sensorValues);

      if (verbose) {
        // verbose output was requested
        Serial.print("AS726x Reading: ");
        Serial.println("R:" + String(sensorValues[AS726x_RED]) + "|O:" + String(sensorValues[AS726x_ORANGE]) + "|Y:" + String(sensorValues[AS726x_YELLOW]) + "|G:" + String(sensorValues[AS726x_GREEN]) + "|B:" + String(sensorValues[AS726x_BLUE]) + "|V:" + String(sensorValues[AS726x_VIOLET]));
      }
      for (int x = 0; x < 6; x++) {
        asReadings[i][x] = sensorValues[x];
      }

      delay(InterCheckDelay);
    }

    // see if the indicator is blinking. this is just an average of all colors per check
    int sensorAvg[NumberOfChecks];
    // first val is highest avg, second is which check
    int highestReading[] = { 0, 0 };
    for (int i = 0; i < NumberOfChecks; i++) {
      int sum = 0;
      for (int x = 0; x < 6; x++) {
        sum = sum + asReadings[i][x];
      }
      sensorAvg[i] = sum / 6;
      // this is used to tell the client what color the indicator is blinking by returning the brightest
      if (sensorAvg[i] > highestReading[0]) {
        highestReading[0] = sensorAvg[i];
        highestReading[1] = i;
      }
    }

    sortArray(sensorAvg, NumberOfChecks);
    if ((sensorAvg[NumberOfChecks - 1] - sensorAvg[0]) > BlinkDiff) {
      // assume a difference of more than BlinkDiff between highest and lowest states means the sensor detected blinking
      Serial.println("Indicator Blinking: R:" + String(asReadings[highestReading[1]][0]) + "|O:" + String(asReadings[highestReading[1]][1]) + "|Y:" + String(asReadings[highestReading[1]][2]) + "|G:" + String(asReadings[highestReading[1]][3]) + "|B:" + String(asReadings[highestReading[1]][4]) + "|V:" + String(asReadings[highestReading[1]][5]));
    }

    else if (sensorAvg[0] < LowerLimit) {
      Serial.println("Indicator Off");
    }

    else {
      // also send colors for client to parse. Just send first reading
      Serial.println("Indicator On: R:" + String(asReadings[0][0]) + "|O:" + String(asReadings[0][1]) + "|Y:" + String(asReadings[0][2]) + "|G:" + String(asReadings[0][3]) + "|B:" + String(asReadings[0][4]) + "|V:" + String(asReadings[0][5]));
    }
  }

  else if (SensorType == "tcs34725") {
    if (!TCS34725Started) {
      Serial.println("ERROR: Cannot connect to TCS34725 sensor");
      return;
    }

    // check sensor
    int asReadings[NumberOfChecks][6];
    for (int i = 0; i < NumberOfChecks; i++) {

      uint16_t r, g, b, c;
      tcs.getRawData(&r, &g, &b, &c);


      if (verbose) {
        // verbose output was requested
        Serial.print("TCS34725 Reading: ");
        Serial.println("R:" + String(r) + "|G:" + String(g) + "|B:" + String(b));
      }
      for (int x = 0; x < 6; x++) {
        asReadings[i][0] = r;
        asReadings[i][1] = g;
        asReadings[i][2] = b;
      }

      delay(InterCheckDelay);
    }

    // see if the indicator is blinking. this is just an average of all colors per check
    int sensorAvg[NumberOfChecks];
    // first val is highest avg, second is which check
    int highestReading[] = { 0, 0 };
    for (int i = 0; i < NumberOfChecks; i++) {
      int sum = 0;
      for (int x = 0; x < 3; x++) {
        sum = sum + asReadings[i][x];
      }
      sensorAvg[i] = sum / 3;
      // this is used to tell the client what color the indicator is blinking by returning the brightest
      if (sensorAvg[i] > highestReading[0]) {
        highestReading[0] = sensorAvg[i];
        highestReading[1] = i;
      }
    }

    sortArray(sensorAvg, NumberOfChecks);
    if ((sensorAvg[NumberOfChecks - 1] - sensorAvg[0]) > BlinkDiff) {
      // assume a difference of more than BlinkDiff between highest and lowest states means the sensor detected blinking
      Serial.println("Indicator Blinking: R:" + String(asReadings[highestReading[1]][0]) + "|G:" + String(asReadings[highestReading[1]][1]) + "|B:" + String(asReadings[highestReading[1]][2]));
    }

    else if (sensorAvg[0] < LowerLimit) {
      Serial.println("Indicator Off");
    }

    else {
      // also send colors for client to parse. Just send first reading
      Serial.println("Indicator On: R:" + String(asReadings[0][0]) + "|G:" + String(asReadings[0][1]) + "|B:" + String(asReadings[0][2]));
    }
  }

  else {
    Serial.println("Error: Invalid sensor type configured!");
  }
}

void loop(void) {

  while (!Serial.available()) {
    // do nothing until serial input is given
  }
  String serInput = Serial.readString();
  serInput.toLowerCase();
  serInput.trim();

  if (serInput.startsWith("status")) {
    if (serInput.endsWith("verbose")) {
      indicatorStatus(true);
    } else {
      indicatorStatus(false);
    }
  }

  else if (serInput == "reboot") {
    Serial.print("Rebooting Device ");
    digitalWrite(RelayPin, HIGH);
    for (int i = 0; i < RebootDelay; i++) {
      Serial.print(".");
      delay(1000);
    }
    digitalWrite(RelayPin, LOW);
    Serial.println("\nReboot Completed");
  }

  else if (serInput == "reset") {
    Serial.println("Resetting controller");
    delay(500);
    pinMode(ResetPin, OUTPUT);
    digitalWrite(ResetPin, LOW);
  }

  else if (serInput == "help") {
    Serial.println("Device Indicator Checker v" + version + "\n");
    Serial.println("All commands are case insensitive. Available commands:");

    Serial.println("ping           - Test serial connection to this device (responds with 'pong')");
    Serial.println("settings       - Show set values");
    Serial.println("status         - Show status of device indicator");
    Serial.println("status verbose - Show status of device indicator and report each measurement");
    Serial.println("reboot         - Reboot attached device");
    Serial.println("help           - Print this menu");
    Serial.println("version        - Print the firmware version");
  }

  else if (serInput == "settings") {
    Serial.println("Device Settings:");
    Serial.print("BlinkDiff: ");
    Serial.println(BlinkDiff);
    Serial.print("InterCheckDelay: ");
    Serial.println(InterCheckDelay);
    Serial.print("LowerLimit: ");
    Serial.println(LowerLimit);
    Serial.print("NumberOfChecks: ");
    Serial.println(NumberOfChecks);
    Serial.print("PhotoresistorPin: ");
    Serial.println(PhotoresistorPin);
    Serial.print("SensorType: ");
    Serial.println(SensorType);
    Serial.print("RelayPin: ");
    Serial.println(RelayPin);
    Serial.print("RebootDelay: ");
    Serial.println(RebootDelay);
  } else if (serInput == "ping") {
    Serial.println("pong");
  }

  else if (serInput == "version") {
    Serial.println("Device Indicator Checker v" + version);
  }

  else {
    Serial.println("Unknown command. Try help?");
  }

  // command finished, send EOT command so the client knows we finished transmitting
  Serial.write(0x04);
  // when used interactivly, send prompt after EOT
  // Serial.write("> ");
}
