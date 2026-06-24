import tkinter as tk
from tkinter import messagebox
import time
import json
import os
import socket
import struct
import numpy as np
import threading

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.dsp_pipeline import process_raw_csi_to_features

class DatasetCollector:
    def __init__(self, root):
        self.root = root
        self.root.title("CSI 降维对齐数据采集器")
        self.root.geometry("500x650")

        # ==== UI 布局 ====
        tk.Label(root, text="第一步: 锁定静态环境指纹 (基线)", font=("Helvetica", 14, "bold"), fg="purple").pack(pady=10)
        self.baseline_btn = tk.Button(root, text="📍 扫描当前空旷房间锁定基线", command=self.set_baseline_mode, font=("Helvetica", 12), bg="#e6e6fa", height=2)
        self.baseline_btn.pack(fill=tk.X, padx=40)
        
        self.baseline_status_label = tk.Label(root, text="[基线状态]: 未锁定 (切勿录制)", font=("Helvetica", 11), fg="red")
        self.baseline_status_label.pack(pady=5)

        tk.Label(root, text="第二步: 选择需要打标的人体动作", font=("Helvetica", 14, "bold")).pack(pady=10)
        self.label_var = tk.StringVar(value="None")
        actions = ["无人环境 (Empty)", "日常走动 (Walking)", "跌倒异常 (Fall)"]
        for act in actions:
            tk.Radiobutton(root, text=act, variable=self.label_var, value=act, font=("Helvetica", 12)).pack(anchor=tk.W, padx=80)

        self.status_label = tk.Label(root, text="状态: 端口已绑定，等待操作", font=("Helvetica", 12), fg="blue")
        self.status_label.pack(pady=15)

        self.packet_count_label = tk.Label(root, text="已捕获对齐样本数: 0", font=("Helvetica", 12))
        self.packet_count_label.pack(pady=5)
        
        self.is_recording = False
        self.is_calibrating = False
        self.baseline_features = None

        self.record_btn = tk.Button(root, text="🔴 开始录制数据 (自动执行差分去噪)", command=self.toggle_recording, font=("Helvetica", 12, "bold"), bg="#f0f0f0", height=2)
        self.record_btn.pack(fill=tk.X, padx=40, pady=10)
        
        # ==== 核心变量 ====
        self.feature_buffer = []
        self.csi_buffer = []

        # ==== UDP 监听 ====
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('0.0.0.0', 8888))
            self.udp_thread = threading.Thread(target=self.udp_listener, daemon=True)
            self.udp_thread.start()
        except OSError:
            messagebox.showerror("端口冲突", "端口 8888 被占用！\n请确保已关闭主服务端 main.py 再运行采集器。")
            sys.exit(1)

    def set_baseline_mode(self):
        self.is_calibrating = True
        self.csi_buffer = []
        self.baseline_btn.config(text="正在采集基线...", bg="yellow")
        self.baseline_status_label.config(text="[基线状态]: 采集中，请保持房间内完全静止...", fg="orange")

    def toggle_recording(self):
        if not self.is_recording:
            if self.baseline_features is None:
                messagebox.showerror("致命错误", "请必须先点击上方按钮锁定【基线】！否则录制的数据分布将与实战冲突！")
                return
            if self.label_var.get() == "None":
                messagebox.showerror("错误", "请先选择一个动作标签!")
                return
            
            self.is_recording = True
            self.record_btn.config(text="⏹ 停止录制并保存至本地", bg="#ffcccc", fg="red")
            self.status_label.config(text=f"正在采集: {self.label_var.get()}...", fg="blue")
            self.feature_buffer = []
            self.csi_buffer = []
            self.packet_count_label.config(text="已捕获对齐样本数: 0")
        else:
            self.is_recording = False
            self.record_btn.config(text="🔴 开始录制数据 (自动执行差分去噪)", bg="#f0f0f0", fg="black")
            self.save_data()

    def udp_listener(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
                if not (self.is_recording or self.is_calibrating):
                    continue

                if len(data) >= 74:
                    magic = struct.unpack('<I', data[:4])[0]
                    if magic == 0x43534921:
                        csi_payload = list(data[10:74])
                        self.csi_buffer.append(csi_payload)

                        # 凑齐 100 个包作为一个处理窗口
                        if len(self.csi_buffer) >= 100:
                            raw_matrix = np.array(self.csi_buffer)
                            self.csi_buffer.clear()
                            
                            feats, spatial_mat, smooth_seq = process_raw_csi_to_features(raw_matrix)
                            features_9d = feats
                            
                            # 【核心修复】基线采集逻辑
                            if self.is_calibrating:
                                self.baseline_features = features_9d
                                self.is_calibrating = False
                                self.root.after(0, lambda: self.baseline_btn.config(text="📍 重新扫描基线", bg="#e6e6fa"))
                                self.root.after(0, lambda: self.baseline_status_label.config(text="[基线状态]: 已完美锁定！✅ 可以开始录制", fg="green"))
                                continue
                            
                            # 【核心修复】差分去噪录制逻辑
                            if self.is_recording and self.baseline_features is not None:
                                features_9d = np.abs(features_9d - self.baseline_features)
                                self.feature_buffer.append(features_9d.tolist())
                                self.root.after(0, lambda: self.packet_count_label.config(text=f"已捕获对齐样本数: {len(self.feature_buffer)}"))
            except Exception as e:
                pass

    def save_data(self):
        if not self.feature_buffer:
            messagebox.showwarning("警告", "未采集到任何数据！请确保 ESP32 正在发包。")
            return

        os.makedirs("datasets", exist_ok=True)
        filename = f"datasets/{self.label_var.get().split(' ')[0]}_{int(time.time())}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                "label": self.label_var.get(),
                "sample_count": len(self.feature_buffer),
                "features_shape": "9 (CV + Baseline_Subtracted)",
                "data": self.feature_buffer
            }, f, ensure_ascii=False, indent=2)
            
        messagebox.showinfo("保存成功", f"完美！成功保存 {len(self.feature_buffer)} 个绝对数学对齐的样本！")
        self.status_label.config(text="录制结束，可以切换下一个动作继续", fg="green")

if __name__ == "__main__":
    root = tk.Tk()
    app = DatasetCollector(root)
    root.mainloop()
