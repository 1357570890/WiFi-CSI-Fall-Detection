#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>

// ====== 硬件保护开关 ======
// 默认设为 true (无天线安全模式)。天线装好后，请务必将其改为 false 以恢复穿墙能力！
#define NO_ANTENNA_SAFE_MODE false
// ==========================

const char* ssid = "wifintellisense";
const char* password = "wifintellisense";

// 终极优化：1Tx3Rx 专属单播模式
// 放弃容易导致瘫痪的广播，改为轮询向 3 个接收端发送单播包
const char* targetIps[] = {
    "192.168.1.102",
    "192.168.1.103",
    "192.168.1.104"
};
const int numTargets = 3;
const int targetPort = 5555;

WiFiUDP udp;
unsigned long txPacketCount = 0;

void setup() {
    Serial.begin(115200);
    Serial.println("Initializing ESP32 CSI Transmitter (Injector)...");

    // 配置 WiFi 为 Station 模式
    WiFi.mode(WIFI_STA);
    
    // 锁定 20MHz 频宽，防止 CSI 子载波数量发生突变 (40MHz 会变成 114 个子载波)
    esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
    
    // 连接并指定锁定在信道 6
    WiFi.begin(ssid, password, 6);
    
    // [安全补丁] 无天线测试期间，强制将发射功率降到最低 (2dBm)，防止烧毁射频功放芯片
    if (NO_ANTENNA_SAFE_MODE) {
        esp_wifi_set_max_tx_power(8);
        Serial.println("\n[警告] 当前运行在无天线安全模式，发射功率已降至最低！");
    } else {
        Serial.println("\n[正常] 天线已就绪，当前运行在全功率模式！");
    }
    
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected.");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
    
    Serial.println("Starting 100Hz packet injection...");
}

void loop() {
    // 轮询向 3 个接收端分别发送单播包，完美避开广播风暴！
    for (int i = 0; i < numTargets; i++) {
        udp.beginPacket(targetIps[i], targetPort);
        udp.write((const uint8_t*)"CSI_PROBE", 9);
        udp.endPacket();
    }
    
    txPacketCount++;
    if (txPacketCount % 100 == 0) {
        Serial.printf("Transmitter: Sent %lu packets.\n", txPacketCount);
    }
    
    delay(10); // 延时 10 毫秒，换算为发送频率约为 100Hz (配合接收端 Batching，毫无压力)
}
