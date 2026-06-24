# 基于 WiFi CSI 的独居老人实时监护与跌倒预警系统 | WiFi CSI Fall Detection

[![Language](https://img.shields.io/badge/Language-C%2B%2B%20%7C%20Python%20%7C%20JavaScript-blue.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)
[![Hardware](https://img.shields.io/badge/Hardware-ESP32-brightgreen.svg)](#)

本工程是 **第二十一届中国研究生电子设计竞赛 / 河南省大学生电子设计竞赛优秀项目** 核心源码。项目实现了基于 WiFi 信道状态信息 (Channel State Information, CSI) 与边缘计算的非接触式动作感知与跌倒预警系统。通过采集 WiFi 射频信号物理层特征，利用深度学习模型实现免穿戴、无隐私泄露的智能跌倒监护。

This project is the core source code of our award-winning work. It implements a non-contact activity recognition and fall detection system using WiFi Channel State Information (CSI) and edge computing, ensuring privacy protection and wearable-free elder care.

---

## 🌟 核心系统架构 / System Architecture

整个系统采用全栈端到端架构，包含数据感知、模型训练、后端汇聚、可视化监控及移动端报警五大部分：

1. **射频感知端 (ESP32 Nodes)**: 基于 C++ (ESP-IDF/Arduino) 开发，发射端高频发送探测数据包，接收端提取子载波 CSI 复数矩阵并以 UDP/Websocket 格式向边缘网关推送。
2. **深度学习训练端 (AI Training)**: 使用 PyTorch 框架，实现 CSI 数据的带阻滤波、PCA降维等预处理，并训练轻量化时空卷积神经网络 (CNN/GRU) 对“跌倒”、“行走”、“坐下”、“躺下”等动作进行高精度分类。
3. **数据处理后端 (Windows Server)**: 采用 Python FastAPI/Flask，高频解析 UDP 原始数据包，进行滑窗滤波和特征提取，载入 PyTorch 模型实现厘米级超低延迟的在线跌倒决策。
4. **可视化监控终端 (Frontend Dashboard)**: 采用 Vanilla JS + ECharts 实时渲染子载波幅值变化波形、动作预测分类概率和设备在线状态。
5. **移动报警小程序 (Mobile App)**: 开发配套的微信小程序，当发生跌倒事件时，通过网络接口发送高优先级微信模板消息推送，实现一秒级家属预警响应。

---

## 📂 项目结构 / Directory Structure

```text
WiFi-CSI-Fall-Detection/
├── 01_esp32_csi_transmitter/ # ESP32 信号发射端源码 / ESP32 CSI transmitter firmware
├── 02_esp32_node/            # ESP32 信号接收与CSI解析器 / ESP32 CSI receiver firmware
├── 03_ai_training/           # 深度学习模型训练与评估 / PyTorch model trainer
│   ├── data_collector.py     # 原始 CSI 数据自动化收集脚本 / Automatic CSI collector
│   ├── train_cnn.py          # 时空卷积网络 CNN 训练脚本 / CNN training script
│   └── dataset/              # 训练数据集目录 / CSI datasets
├── 04_models/                # 已训练的深度学习模型权重 / Trained model weights (.pth)
├── 05_windows_server/        # 局域网边缘网关/服务器后端 / Python socket & HTTP server
│   ├── main.py               # 实时 UDP 数据流订阅与推理服务 / Real-time inference engine
│   └── dataset_tool/         # 数据清洗与导出脚本 / Dataset parser
├── 06_frontend_dashboard/    # 实时波形与监测 Web 仪表盘 / ECharts Web monitor
└── 07_mobile_app/            # 微信小程序端报警界面源码 / WeChat Mini-Program source code
```

---

## 🛠️ 快速开始 / Quick Start

### 1. 烧录 ESP32 节点
- 发射端：将 `01_esp32_csi_transmitter` 导入 PlatformIO 或 Arduino IDE 烧录进 ESP32 开发板。
- 接收端：烧录 `02_esp32_node`，确保接收端与发射端处于相同信道（如信道 6）。

### 2. 启动数据推理后端
在服务器或边缘 PC (与接收端处于同一局域网) 运行：
```bash
cd 05_windows_server
pip install -r requirements.txt
python main.py
```
这会拉起一个 UDP 监听服务（默认端口 8080）来接收 ESP32 推送的 CSI 字节流，并提供实时识别 WebSocket 接口。

### 3. 打开 Web 控制台
双击打开 `06_frontend_dashboard/index.html`，输入服务器的 IP 地址即可实时观测 CSI 信号强度变化和行为检测分类。

---

## ⚙️ 模型表现 / Model Performance
- **算法模型**：时空 CNN / 1D-CNN ResNet 变体
- **输入维度**：每个数据包包含 64 个子载波的幅值和相位
- **识别准确率**：实验室环境下，防跌倒判别准确率达到 **94% 以上**，具备极强的鲁棒性，有效过滤翻身、坐下等类似姿态的干扰。
