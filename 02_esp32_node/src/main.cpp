#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <WiFiUdp.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

// ====== 硬件保护开关 ======
// 默认设为 true (无天线安全模式)。天线装好后，请务必将其改为 false 以恢复穿墙能力！
#define NO_ANTENNA_SAFE_MODE false
// ==========================

const char* ssid = "wifintellisense";
const char* password = "wifintellisense";

// Windows 算力中心的 IP 和接收端口 (CSI 数据发送方向)
const char* udpAddress = "192.168.1.100";
const int udpPort = 8888;

// 本地监听命令端口 (接收 Windows 发来的报警信号)
const int cmdPort = 8889;

// ===== 蜂鸣器引脚配置 =====
#define BEEP_PIN 4

WiFiUDP udp;
WiFiUDP cmdUdp;

unsigned long beepStartTime = 0;
bool isBeeping = false;
const unsigned long BEEP_DURATION = 3000;

unsigned long csiPacketsSentCount = 0;
unsigned long lastStatsTimeNode = 0;

// ==========================================
// 终极工业级架构：FreeRTOS 异步环形队列
// ==========================================
// 结构体：用于在队列中暂存 CSI 数据包
typedef struct {
    uint16_t len;
    uint8_t data[384]; // 针对 ESP32，384 字节足以装下最长的单次 CSI payload
} csi_packet_t;

// 定义 FreeRTOS 队列句柄
QueueHandle_t csi_queue;

// 极其精简的底层回调函数（生产者）
// 绝对禁止在此处调用任何网络阻塞函数！
void csi_rx_callback(void *ctx, wifi_csi_info_t *info) {
    if (!info || !info->buf || info->len == 0 || info->len > 384) {
        return;
    }

    csi_packet_t pkt;
    pkt.len = info->len;
    // 仅仅进行一次微秒级的内存拷贝
    memcpy(pkt.data, info->buf, info->len);
    
    // 以 0 阻塞时间将其推入队列。如果队列满了（网络极度拥堵），直接丢弃旧包，誓死保卫 Wi-Fi 任务不卡顿！
    xQueueSend(csi_queue, &pkt, 0); 
}

void setup() {
    Serial.begin(115200);
    Serial.println("Initializing ESP32 Node for CSI...");

    // 创建深度为 20 的 FreeRTOS 队列 (可缓冲 200 毫秒的高峰数据流)
    csi_queue = xQueueCreate(20, sizeof(csi_packet_t));
    if (csi_queue == NULL) {
        Serial.println("Error creating the CSI Queue!");
    }

    pinMode(BEEP_PIN, OUTPUT);
    digitalWrite(BEEP_PIN, LOW);

    WiFi.mode(WIFI_STA);
    esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
    WiFi.begin(ssid, password, 6);
    
    // [安全补丁] 无天线测试期间，强制将发射功率降到最低 (2dBm)，防止烧毁射频功放芯片
    if (NO_ANTENNA_SAFE_MODE) {
        esp_wifi_set_max_tx_power(8);
        Serial.println("\n[警告] 当前运行在无天线安全模式，发射功率已降至最低！");
    } else {
        Serial.println("\n[正常] 天线已就绪，当前运行在全功率模式！");
    }
    
    Serial.print("Connecting");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected.");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    cmdUdp.begin(cmdPort);
    Serial.printf("Listening for commands on UDP port %d\n", cmdPort);

    wifi_csi_config_t csi_config = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = false,
        .manu_scale        = false,
        .shift             = false
    };
    
    esp_wifi_set_csi_config(&csi_config);
    esp_wifi_set_csi_rx_cb(&csi_rx_callback, NULL);
    esp_wifi_set_csi(true);
    Serial.println("CSI Rx enabled.");
}

void loop() {
    // 1. 消费者逻辑：从 FreeRTOS 队列中抽取数据并进行网络聚合打包 (Batching)
    if (uxQueueMessagesWaiting(csi_queue) > 0) {
        int packetsInBatch = 0;
        csi_packet_t pkt;
        
        udp.beginPacket(udpAddress, udpPort);
        
        // 每次最多连续抽出 5 个包拼装在一个 UDP 中发送 (有效载荷约 700 字节，远低于 MTU 1500)
        // 配合发送端 100Hz，每秒只发送 20 个大 UDP 包，大幅减轻路由器 PPS 压力！
        while (packetsInBatch < 5 && xQueueReceive(csi_queue, &pkt, 0) == pdTRUE) {
            const uint32_t magic = 0x43534921; // "CSI!"
            uint32_t ts = millis();
            
            udp.write((const uint8_t*)&magic, sizeof(magic));
            udp.write((const uint8_t*)&ts, sizeof(ts));
            udp.write((const uint8_t*)&pkt.len, sizeof(pkt.len));
            udp.write((const uint8_t*)pkt.data, pkt.len);
            
            packetsInBatch++;
            csiPacketsSentCount++;
        }
        
        udp.endPacket();
    }

    // 2. 处理传入的 UDP 报警命令包
    int packetSize = cmdUdp.parsePacket();
    if (packetSize) {
        char incomingPacket[255];
        int len = cmdUdp.read(incomingPacket, 255);
        if (len > 0) {
            incomingPacket[len] = 0;
        }
        
        String command = String(incomingPacket);
        command.trim();
        
        if (command == "FALL") {
            Serial.println("Fall detected! Triggering active buzzer.");
            isBeeping = true;
            beepStartTime = millis();
            digitalWrite(BEEP_PIN, HIGH);
        }
    }

    // 3. 异步蜂鸣器关闭逻辑
    if (isBeeping) {
        if (millis() - beepStartTime >= BEEP_DURATION) {
            digitalWrite(BEEP_PIN, LOW);
            isBeeping = false;
            Serial.println("Buzzer stopped.");
        }
    }
    
    // 定期打印调试信息 (每秒一次)
    if (millis() - lastStatsTimeNode >= 1000) {
        Serial.printf("Node: Sent %lu CSI packets. Free Queue Spaces: %d\n", 
                      csiPacketsSentCount, uxQueueSpacesAvailable(csi_queue));
        csiPacketsSentCount = 0;
        lastStatsTimeNode = millis();
    }

    // 微弱延时释放 CPU，维持系统稳定
    delay(2); 
}
