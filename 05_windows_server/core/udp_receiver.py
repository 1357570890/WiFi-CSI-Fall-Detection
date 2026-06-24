import asyncio
import struct
import time
import numpy as np
from core.dsp_pipeline import process_raw_csi_to_features
from core.ai_engine import FallDetectionModel
from core.global_state import manager, current_status
from core.llm_notifier import llm_notifier

ai_model = FallDetectionModel()

# 动态注册的节点列表
REGISTERED_NODES = []

# 跌倒报警锁死状态机 (用于解决跌倒后静止导致的报警瞬间消失问题)
ALARM_LATCH = {
    "is_active": False,
    "trigger_time": 0.0,
    "duration": 6.0  # 锁定 6 秒，确保大屏和手机有充足时间展示刺眼的红色警报
}

# ========================================================
# 1. 多节点融合计算 
# ========================================================
def process_matrix_sync(synced_matrices, transport):
    """
    处理对齐后的 N 个节点的矩阵 (自适应 1Rx/2Rx/3Rx)
    """
    node_waveforms = {}
    node_energies = {}
    
    # 严格按照 IP 排序提取特征，保证通道顺序永远固定
    active_nodes = sorted(list(synced_matrices.keys()))
    num_rx = len(active_nodes)
    
    node_features = {}
    node_waveforms = {}
    node_waveforms_display = {}
    
    for addr in active_nodes:
        raw_matrix = synced_matrices[addr]
        # 单节点提取 10D 统计特征, 二维时空特征图(11x100) 和 平滑后的真实一维波形
        feats, spatial_mat, smooth_seq = process_raw_csi_to_features(raw_matrix)
        node_features[addr] = feats.tolist()
        node_waveforms[addr] = spatial_mat
        node_waveforms_display[addr] = smooth_seq.tolist() # 用于推送到前端大屏画图的 1D 波形
        # 精确对齐历史特征提取逻辑：计算 标准差(std)
        node_energies[addr] = float(np.std(smooth_seq))  
        
    # 构建特征张量和波形张量
    features_nd = np.array(list(node_features.values()))
    # node_waveforms[addr] 已经是 (11, 100) 的矩阵，将多个节点的矩阵沿通道拼接，变成 (rx_num*11, 100)
    waveforms_nd = np.vstack(list(node_waveforms.values()))
    
    # 直接送入支持多维度的 AI 引擎
    pred_idx, pred_label, confidence = ai_model.predict(waveforms_nd, features_nd)
    
    # 获取最大的单节点能量扰动
    max_energy = max(node_energies.values()) if node_energies else 0.0
    
    #  物理增强型专家引擎 (Physics-Informed Rules)
    # 彻底移除基于经验的“能量锁”，因为 MLP 已使用了 9 维统计特征进行极高精度的自主分类！
    # 直接使用模型原生的超高准确率结果。
    # 规则2：跌倒置信度衰减锁。在确实有运动的情况下，如果跌倒置信度低于 40%，才降级为走动
    if pred_idx == 3 and confidence < 0.40:
        pred_idx, pred_label = 2, "日常活动"
            
    # 🚨 状态锁死状态机 (Alarm Latching)
    current_time = time.time()
    if pred_idx == 3:
        ALARM_LATCH["is_active"] = True
        ALARM_LATCH["trigger_time"] = current_time
        
    trigger_fall = False
    # 如果处于跌倒报警锁定期，强制覆写当前状态为跌倒
    if ALARM_LATCH["is_active"]:
        if current_time - ALARM_LATCH["trigger_time"] < ALARM_LATCH["duration"]:
            pred_idx, pred_label = 3, "危险！跌倒异常"
            trigger_fall = True
            max_amp = max_energy
            # 暂不实施告警频率限流，确保在高危跌倒状态下大模型能够持续追踪目标状态
            llm_notifier.trigger_fall_alert(confidence=confidence, max_amp=max_amp)
        else:
            ALARM_LATCH["is_active"] = False # 锁定期结束，释放状态机

    # 将 node_waveforms_display 返回给 FastAPI，这样 json_dumps 就可以安全序列化 list
    return pred_idx, pred_label, confidence, trigger_fall, num_rx, node_waveforms_display, node_energies


# ========================================================
# 2. 消费者任务：从队列抽取对齐的数据包
# ========================================================
async def process_queue_worker(processing_queue, protocol_instance):
    print("Adaptive AI Consumer Worker started.")
    while True:
        synced_matrices = await processing_queue.get()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, process_matrix_sync, synced_matrices, protocol_instance.transport)
            
            if result:
                pred_idx, pred_label, confidence, trigger_fall, num_rx, waveforms, energies = result
                
                # 如果检测到跌倒，向所有活跃接收节点广播报警信号，让蜂鸣器响
                if trigger_fall and protocol_instance.transport:
                    for addr in synced_matrices.keys():
                        protocol_instance.transport.sendto(b"FALL", (addr, 8889))
                
                # 更新前端大屏的整体状态，前缀自适应
                prefix = f"[{num_rx}Rx 全息感知]" if num_rx == 3 else f"[{num_rx}Rx 融合]" if num_rx == 2 else f"[{num_rx}Rx 感知]"
                current_status["status"] = f"{prefix} {pred_label}" 
                current_status["status_code"] = pred_idx
                current_status["active_nodes"] = num_rx
                current_status["waveforms"] = waveforms
                current_status["energies"] = energies
                asyncio.create_task(manager.broadcast(current_status))
                
        except Exception as e:
            print(f"Error processing matrix: {e}")
        finally:
            processing_queue.task_done()


# ========================================================
# 3. 生产者：全局时序对齐接收引擎
# ========================================================
class CsiUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, processing_queue):
        super().__init__()
        self.processing_queue = processing_queue
        self.transport = None
        
        self.packet_counts = {}
        self.start_times = {}
        self.csi_buffers = {}
        
        self.sync_window_size = 100 # 每 100 帧视为一个时间对齐窗口

    def connection_made(self, transport):
        self.transport = transport
        print(f"Adaptive UDP Receiver listening on {transport.get_extra_info('sockname')}")

    def datagram_received(self, data, addr):
        if len(data) < 10: return

        try:
            addr_ip = addr[0]
            
            # --- 动态节点注册机制 ---
            if addr_ip not in REGISTERED_NODES:
                if len(REGISTERED_NODES) < 3:
                    REGISTERED_NODES.append(addr_ip)
                    REGISTERED_NODES.sort()
                    print(f"\n[Node Auto-Register] 节点 {addr_ip} 接入。当前活跃 {len(REGISTERED_NODES)}/3 个。")
                    self.csi_buffers[addr_ip] = []
                    self.packet_counts[addr_ip] = 0
                    self.start_times[addr_ip] = time.time()
                else:
                    return

            # --- 创新点：支持 Batching 多级拆包 ---
            # 循环切香肠，把同一个 UDP 包里的多个 CSI 数据一帧一帧切出来
            offset = 0
            while offset + 10 <= len(data):
                magic, ts, csi_len = struct.unpack('<IIH', data[offset:offset+10])
                if magic != 0x43534921:
                    break # 魔法字不对，说明后面的数据不是标准格式，停止解析当前包的剩余部分
                    
                if offset + 10 + csi_len > len(data):
                    break # 数据包不完整，截断丢失
                    
                csi_payload = data[offset+10 : offset+10+csi_len]
                offset += 10 + csi_len # 游标前进
                
                if len(csi_payload) < 128: 
                    continue

                raw_array = np.frombuffer(csi_payload, dtype=np.int8)[:128]
                i_vals = raw_array[0::2].astype(np.float32)
                q_vals = raw_array[1::2].astype(np.float32)
                amplitude = np.sqrt(i_vals**2 + q_vals**2)
                
                self.csi_buffers[addr_ip].append(amplitude.tolist())
                self.packet_counts[addr_ip] += 1
            
            current_time = time.time()
            if current_time - self.start_times[addr_ip] >= 1.0:
                print(f"[{time.strftime('%H:%M:%S')}] [{addr_ip}] Rx Rate: {self.packet_counts[addr_ip]} pkts/s (Batched)")
                self.start_times[addr_ip] = current_time
                self.packet_counts[addr_ip] = 0

            # --- 严格的多节点全局时间同步 ---
            # 必须等待所有已注册节点都攒够 100 帧，才能触发联合推理，防止 2Rx 降级为 1Rx
            ready_nodes = [node for node in REGISTERED_NODES if len(self.csi_buffers[node]) >= self.sync_window_size]
            
            if len(REGISTERED_NODES) > 0 and len(ready_nodes) == len(REGISTERED_NODES):
                synced_matrices = {}
                overlap = self.sync_window_size // 2  # 滑动窗口重叠 50 帧
                
                for node in ready_nodes:
                    synced_matrices[node] = np.array(self.csi_buffers[node][:self.sync_window_size])
                    # --- 修复 2：滑动窗口机制 ---
                    # 以前是丢弃全部 100 帧，导致长达 2.5 秒的更新延迟
                    # 现在只丢弃前 50 帧，保留后 50 帧，使得刷新速度翻倍！
                    self.csi_buffers[node] = self.csi_buffers[node][overlap:]
                    
                try:
                    self.processing_queue.put_nowait(synced_matrices)
                except asyncio.QueueFull:
                    print("[Sync Error] Queue is full, dropping synchronized frame batch!")

        except Exception as e:
            print(f"UDP Error: {e}")

async def node_watchdog(protocol_instance):
    """
    自适应看门狗：如果 3 秒没收到某个节点的数据，认为其已断电/拔出，将其踢出注册表。
    """
    while True:
        await asyncio.sleep(1.0)
        current_time = time.time()
        disconnected_nodes = []
        for node in list(REGISTERED_NODES):
            # 获取节点最后一次收到包更新的 start_times 或者是最新的一笔包的时间（近似处理：若超时3秒）
            # 注意：start_times 是每秒打印 Rx Rate 时更新的。如果断线，就会永远停在旧时间。
            if current_time - protocol_instance.start_times.get(node, current_time) > 3.0:
                disconnected_nodes.append(node)
        
        for node in disconnected_nodes:
            print(f"\n[{time.strftime('%H:%M:%S')}] [Watchdog] 警告: 节点 {node} 失去响应 (已离线)！踢出联邦网络。")
            REGISTERED_NODES.remove(node)
            if node in protocol_instance.csi_buffers: del protocol_instance.csi_buffers[node]
            if node in protocol_instance.packet_counts: del protocol_instance.packet_counts[node]
            if node in protocol_instance.start_times: del protocol_instance.start_times[node]
                
        # 如果彻底没节点了，广播系统待机
        if len(REGISTERED_NODES) == 0 and current_status["status_code"] != -1:
            current_status["status"] = "[系统待机] 0 节点连接"
            current_status["status_code"] = -1
            current_status["active_nodes"] = 0
            asyncio.create_task(manager.broadcast(current_status))


async def start_udp_server():
    loop = asyncio.get_running_loop()
    processing_queue = asyncio.Queue()
    protocol_instance = CsiUdpProtocol(processing_queue)
    
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: protocol_instance,
        local_addr=('0.0.0.0', 8888)
    )
    asyncio.create_task(process_queue_worker(processing_queue, protocol_instance))
    asyncio.create_task(node_watchdog(protocol_instance))
