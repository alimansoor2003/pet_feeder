/*
 * PawSense Feeder — ESP32 firmware
 * --------------------------------
 * Consumer-grade onboarding: NOTHING network-specific is flashed into
 * this sketch. The customer experience on any Wi-Fi, in any house:
 *
 *   1. Plug the feeder in. On first boot (or after "Reset Wi-Fi") it
 *      broadcasts its own hotspot named "PawSense-Setup".
 *   2. Customer connects to that hotspot with their phone — a setup
 *      page pops up automatically (captive portal), they pick their
 *      home Wi-Fi and type its password. The feeder remembers it.
 *   3. Customer claims the feeder on the website using the sticker
 *      (Device ID + Setup Key). Done — Feed Now works.
 *
 * Moving to a new house/Wi-Fi: hold the reset-wifi button 5 seconds,
 * the hotspot comes back, repeat step 2. Firmware never re-flashed.
 *
 * The ONLY thing you customize per unit before flashing is the identity
 * block below (from Admin -> Devices -> "+ Provision New Device" — the
 * same pair you print on the unit's sticker).
 *
 * Server address: fixed public URL, identical for every unit, works
 * from any network. Point it at your ngrok static domain now; swap to
 * your real domain when you move to a VPS — one line, all units same.
 *
 * Libraries (Arduino IDE -> Library Manager):
 *   - "WiFiManager" by tzapu  (the captive-portal magic)
 *   - "ArduinoJson" by Benoit Blanchon
 *   Board: "ESP32 Dev Module" (install "esp32 by Espressif" in Boards
 *   Manager if missing).
 */

#include <WiFiManager.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ==== IDENTITY OF THIS UNIT — from admin provisioning, matches sticker ====
const char* DEVICE_ID = "dev_REPLACE_ME";
const char* API_KEY   = "XXXX-XXXX-XXXX";

// ==== SERVER — same for every unit, never changes with customer Wi-Fi ====
// Your ngrok static domain (claim it free at dashboard.ngrok.com -> Domains),
// e.g. "https://alim-pawsense.ngrok-free.dev". Later: your VPS domain.
const char* SERVER_BASE = "https://REPLACE-ME.ngrok-free.dev";

// ==== HARDWARE PINS ====
const int FEED_MOTOR_PIN  = 26;   // servo/relay that dispenses food
const int WIFI_RESET_PIN  = 0;    // BOOT button: hold 5s to redo Wi-Fi setup
const int STATUS_LED_PIN  = 2;    // onboard LED: solid = online, blink = setup

// ==== TIMING ====
const unsigned long POLL_INTERVAL_MS      = 5000;    // ask "should I feed?"
const unsigned long HEARTBEAT_INTERVAL_MS = 30000;   // prove we're alive

unsigned long lastPoll = 0;
unsigned long lastHeartbeat = 0;
unsigned long resetHeldSince = 0;

WiFiClientSecure tls;

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  pinMode(FEED_MOTOR_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(WIFI_RESET_PIN, INPUT_PULLUP);

  // Captive-portal onboarding. If saved Wi-Fi credentials exist it just
  // connects; otherwise it opens the "PawSense-Setup" hotspot and waits
  // for the customer. Credentials persist in flash across power cycles.
  WiFiManager wm;
  wm.setConfigPortalTimeout(300);  // retry connect if nobody configures in 5 min
  digitalWrite(STATUS_LED_PIN, HIGH);
  if (!wm.autoConnect("PawSense-Setup")) {
    ESP.restart();  // portal timed out — reboot and try the saved network again
  }
  digitalWrite(STATUS_LED_PIN, LOW);
  Serial.println("WiFi connected: " + WiFi.localIP().toString());

  // ngrok terminates real TLS for us; skipping cert validation on-device
  // keeps the sketch simple. When you move to your own domain, pin the
  // certificate here (tls.setCACert) for production-grade security.
  tls.setInsecure();
}

// ---------------------------------------------------------------------------

bool apiCall(const char* method, const String& path, String& responseOut) {
  HTTPClient http;
  http.setReuse(true);  // keep the TLS connection alive between polls
  if (!http.begin(tls, String(SERVER_BASE) + path)) return false;
  http.addHeader("X-API-Key", API_KEY);
  http.addHeader("ngrok-skip-browser-warning", "1");  // bypass ngrok's browser page

  int status = (strcmp(method, "POST") == 0) ? http.POST("") : http.GET();
  if (status > 0) responseOut = http.getString();
  http.end();

  if (status == 401) Serial.println("! API key rejected — flashed identity doesn't match server");
  if (status == 404) Serial.println("(unclaimed — waiting for customer to enter sticker codes)");
  return status == 200;
}

void dispenseFood() {
  Serial.println(">>> FEEDING <<<");
  // MVP: pulse the motor/servo relay for 2 seconds. Replace with your
  // actual dispensing mechanism (servo sweep, auger turns, etc.).
  digitalWrite(FEED_MOTOR_PIN, HIGH);
  delay(2000);
  digitalWrite(FEED_MOTOR_PIN, LOW);

  String ignored;
  apiCall("POST", String("/api/device/") + DEVICE_ID + "/ack", ignored);
}

void checkWifiResetButton() {
  // Hold BOOT for 5 seconds -> wipe saved Wi-Fi, reboot into setup hotspot.
  if (digitalRead(WIFI_RESET_PIN) == LOW) {
    if (resetHeldSince == 0) resetHeldSince = millis();
    if (millis() - resetHeldSince > 5000) {
      Serial.println("Wi-Fi reset requested — reopening setup hotspot");
      WiFiManager wm;
      wm.resetSettings();
      ESP.restart();
    }
  } else {
    resetHeldSince = 0;
  }
}

// ---------------------------------------------------------------------------

void loop() {
  checkWifiResetButton();

  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(STATUS_LED_PIN, millis() / 500 % 2);  // blink while reconnecting
    delay(100);
    return;
  }
  digitalWrite(STATUS_LED_PIN, HIGH);  // solid = online

  if (millis() - lastHeartbeat > HEARTBEAT_INTERVAL_MS || lastHeartbeat == 0) {
    lastHeartbeat = millis();
    String ignored;
    apiCall("POST", String("/api/device/") + DEVICE_ID + "/heartbeat", ignored);
  }

  if (millis() - lastPoll > POLL_INTERVAL_MS) {
    lastPoll = millis();
    String body;
    if (apiCall("GET", String("/api/device/") + DEVICE_ID + "/commands", body)) {
      JsonDocument doc;
      if (deserializeJson(doc, body) == DeserializationError::Ok && doc["feed"] == true) {
        dispenseFood();
      }
    }
  }

  delay(50);
}
