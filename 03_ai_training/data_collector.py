import socket
import struct
import numpy as np
import pandas as pd
import time
import os
import argparse
import argparse
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# UDP 配置
UDP_IP = "0.0.0.0"
UDP_PORT = 8888

# 类别定义 (必须与服务端 AI Engine 严格对齐)
CLASSES = {
    0: "Empty (无人)",
    1: "Sitting (原地静坐)",
    2: "Walk (日常走动)",
    3: "Fall (跌倒异常)"
}

def start_collection(label: int, duration: int, output_file: str, rx_num: int):
    print(f"=====================================")
    print(f"🎯 CSI 数据采集系统启动 ({rx_num}Rx 模式 + 实时可视化)")
    print(f"📊 采集动作: {CLASSES[label]}")
    print(f"⏱️  采集时长: {duration} 秒")
    print(f"💾 输出文件: {output_file}")
    print(f"=====================================")
    print("请走到测试区域准备，3秒后开始录制...")
    time.sleep(3)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 允许端口复用（如果 Server 也在跑，尽量不要冲突）
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((UDP_IP, UDP_PORT))
    except OSError as e:
        print(f"\n❌ 端口绑定失败 ({e})！\n请检查是否正在运行后端大屏 (main.py)，同一时间只能有一个程序占用 UDP 8888 端口接收底层数据。请先关闭 Server 再录制。")
        return

    sock.settimeout(1.0)
    
    print("\n🟢 [录制中...] 请持续做动作...")
    
    dataset = []
    csi_buffers = {}
    start_time = time.time()
    last_print_time = start_time
    packet_count = 0
    
    while True:
        current_time = time.time()
        elapsed = current_time - start_time
        if elapsed >= duration:
            break
            
        # 每秒更新一次进度条，末尾增加空格防止 \r 导致的字符残留（视觉Bug）
        if current_time - last_print_time >= 1.0:
            print(f"\r⏳ 倒计时: {int(duration - elapsed):>2} 秒 | 接收状态: 正常 ✅ | 已获取对齐帧: {packet_count}      ", end="", flush=True)
            last_print_time = current_time
            
        try:
            data, addr = sock.recvfrom(4096)
            ip = addr[0]
            
            # 动态发现并注册节点
            if ip not in csi_buffers:
                if len(csi_buffers) < rx_num:
                    csi_buffers[ip] = []
                    print(f"\n📌 发现新节点: {ip} ({len(csi_buffers)}/{rx_num})")
                else:
                    continue # 忽略多余节点
                    
            # 批量解包 (Batching)
            offset = 0
            while offset + 10 <= len(data):
                magic, ts, csi_len = struct.unpack('<IIH', data[offset:offset+10])
                if magic != 0x43534921:
                    break
                    
                csi_data = data[offset+10:offset+10+csi_len]
                offset += 10 + csi_len
                
                raw_array = np.frombuffer(csi_data, dtype=np.int8)
                if len(raw_array) >= 128:
                    raw_array = raw_array[:128] # 截取前 64 个子载波
                    i_vals = raw_array[0::2].astype(np.float32)
                    q_vals = raw_array[1::2].astype(np.float32)
                    amplitude = np.sqrt(i_vals**2 + q_vals**2)
                    csi_buffers[ip].append(amplitude)
            
            # 多节点时间对齐 (Time Sync)
            if len(csi_buffers) == rx_num:
                while all(len(buf) > 0 for buf in csi_buffers.values()):
                    sorted_ips = sorted(list(csi_buffers.keys()))
                    row_data = []
                    plot_vals = []
                    
                    for s_ip in sorted_ips:
                        amp_array = csi_buffers[s_ip].pop(0)
                        row_data.extend(amp_array.tolist())
                        
                    row_data.append(label)
                    dataset.append(row_data)
                    packet_count += 1
                    
        except socket.timeout:
            continue
        except Exception as e:
            print(f"⚠️ 解析错误: {e}")

    sock.close()
    print(f"\n🔴 [录制结束] 耗时: {duration} 秒，共收集 {packet_count} 帧同步后 CSI 数据。")
    
    if packet_count > 0:
        action_name = CLASSES[label].split(' ')[0]
        base_dir = os.path.dirname(output_file)
        
        # 加入时间戳，让每一次录制都生成独立的文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_name = os.path.basename(output_file).replace(".csv", f"_{label}_{action_name}_{timestamp}.csv")
        actual_output_file = os.path.join(base_dir, f"{rx_num}rx", file_name)
        
        os.makedirs(os.path.dirname(actual_output_file), exist_ok=True)
        df = pd.DataFrame(dataset)
        df.to_csv(actual_output_file, mode='w', header=False, index=False)
        print(f"✅ 数据已保存至独立文件 {actual_output_file}，文件总大小: {os.path.getsize(actual_output_file)/1024:.2f} KB\n")
    else:
        print("⚠️ 警告：未收集到任何有效同步数据！请检查接收端是否已开启并联通网络。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESP32 CSI 动作数据采集器")
    parser.add_argument("-l", "--label", type=int, required=True, help="采集动作标签 (0:无人, 1:静坐, 2:走动, 3:跌倒)")
    parser.add_argument("-t", "--time", type=int, default=30, help="持续采集时间(秒)，默认30秒")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_output = os.path.join(current_dir, "dataset", "raw_csi_dataset.csv")
    parser.add_argument("-o", "--output", type=str, default=default_output, help="输出 CSV 文件路径")
    parser.add_argument("--rx", type=int, choices=[1, 2, 3], default=1, help="同时采集的接收端数量 (1-3)")
    
    args = parser.parse_args()
    if args.label not in CLASSES:
        print("❌ 错误：未知的标签！必须是 0, 1, 2, 3 中的一个。")
    else:
        start_collection(args.label, args.time, args.output, args.rx)
