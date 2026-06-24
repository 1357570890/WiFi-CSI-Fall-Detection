import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
import sys
import os

# 将父目录加入系统路径，以便跨目录引用生产环境的 core 模块
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "05_windows_server"))
from core.dsp_pipeline import process_raw_csi_to_features

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import argparse

# ================================
# 超参数配置
# ================================
BATCH_SIZE = 64
EPOCHS = 100
LEARNING_RATE = 0.001

# ================================
# 1. 自定义数据集 (包含 DSP 预处理)
# ================================
class CSIDataset(Dataset):
    def __init__(self, data_path, rx_num=1, mode='train'):
        self.rx_num = rx_num
        self.mode = mode
        import glob
        
        processed_features = []
        processed_sequences = []
        new_labels = []
        
        if os.path.isdir(data_path):
                rx_dir = os.path.join(data_path, f"{self.rx_num}rx")
                if os.path.exists(rx_dir):
                    csv_files = glob.glob(os.path.join(rx_dir, "*.csv"))
                    if mode == 'train':
                        print(f"Loading raw data from directory {rx_dir}, found {len(csv_files)} files...")
                else:
                    csv_files = glob.glob(os.path.join(data_path, "*.csv")) # Fallback
                    if mode == 'train':
                        print(f"Fallback: Loading raw data from directory {data_path}, found {len(csv_files)} files...")
            else:
                csv_files = [data_path]
                if mode == 'train':
                    print(f"Loading raw data from file {data_path}...")
                
            if not csv_files:
                raise ValueError(f"No CSV files found in {data_path}")
            
            if mode == 'train':
                print("Running DSP Pipeline (Sliding Time Window) and applying Hard Sequential Split...")
            
            window_size = 100
            step = 10  # 滑动窗口步长
            
            for f in csv_files:
                try:
                    df = pd.read_csv(f, header=None)
                except pd.errors.EmptyDataError:
                    continue
                    
                num_features = 64 * self.rx_num
                raw_x = df.iloc[:, :num_features].values
                file_labels = df.iloc[:, num_features].values
                
                num_windows = (len(raw_x) - window_size) // step + 1
                if num_windows <= 0:
                    continue
                    
                file_features = []
                file_sequences = []
                file_lbls = []
                
                from tqdm import tqdm
                for i in tqdm(range(num_windows), desc=f"Processing {f[-25:]}", leave=False):
                    chunk = raw_x[i*step : i*step + window_size]
                    window_labels = file_labels[i*step : i*step + window_size]
                    label = np.bincount(window_labels).argmax()
                    
                    features_list = []
                    sequences_list = []
                    for rx_idx in range(self.rx_num):
                        start_col = rx_idx * 64
                        end_col = start_col + 64
                        if end_col > chunk.shape[1]:
                            padded_chunk = np.zeros((chunk.shape[0], 64))
                            actual_width = chunk.shape[1] - start_col
                            if actual_width > 0:
                                padded_chunk[:, :actual_width] = chunk[:, start_col:]
                            feats, spatial_mat, smooth_seq = process_raw_csi_to_features(padded_chunk)
                        else:
                            feats, spatial_mat, smooth_seq = process_raw_csi_to_features(chunk[:, start_col:end_col])
                        features_list.extend(feats.tolist())
                        sequences_list.append(spatial_mat)
                        
                    features = np.array(features_list) # shape: (rx_num * 10,)
                    sequences = np.vstack(sequences_list) # shape: (rx_num * 11, 100)
                    file_features.append(features)
                    file_sequences.append(sequences)
                    file_lbls.append(label)
                    
                processed_features.extend(file_features)
                processed_sequences.extend(file_sequences)
                new_labels.extend(file_lbls)
                
        # 打乱并随机切分 80/20，验证模型对同分布数据的拟合上限
        dataset_size = len(processed_features)
        indices = np.random.permutation(dataset_size)
        split_idx = int(0.8 * dataset_size)
        
        train_idx, test_idx = indices[:split_idx], indices[split_idx:]
        
        if self.mode == 'train':
            self.x_data = torch.tensor(np.array(processed_features)[train_idx], dtype=torch.float32)
            self.seq_data = torch.tensor(np.array(processed_sequences)[train_idx], dtype=torch.float32)
            self.y_data = torch.tensor(np.array(new_labels)[train_idx], dtype=torch.long)
        else:
            self.x_data = torch.tensor(np.array(processed_features)[test_idx], dtype=torch.float32)
            self.seq_data = torch.tensor(np.array(processed_sequences)[test_idx], dtype=torch.float32)
            self.y_data = torch.tensor(np.array(new_labels)[test_idx], dtype=torch.long)
        
        self.labels = self.y_data.tolist()
        if len(self.labels) == 0:
            if mode == 'train':
                print(f"⚠️ {mode} 模式下未能提取到有效窗口！")
            return
        
        if mode == 'train':
            print(f"Data processed! Training windows: {len(self.labels)}")
        else:
            print(f"Data processed! Testing windows: {len(self.labels)}")

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        feats = self.x_data[idx]
        seqs = self.seq_data[idx].clone()
        label = self.y_data[idx]
        
        if self.mode == 'train':
            # Jittering (Gaussian Noise)
            noise = torch.randn_like(seqs) * 0.02
            seqs = seqs + noise
            
            # Scaling
            scale = torch.empty(1).uniform_(0.8, 1.2).item()
            seqs = seqs * scale
            
        return seqs, feats, label

# ================================
# 2. 训练管线
# ================================
def train(data_path, rx_num):
    if not os.path.exists(data_path):
        print(f"❌ 找不到数据集 {data_path}！请先运行 data_collector.py 收集数据。")
        return
        
    train_dataset = CSIDataset(data_path, rx_num=rx_num, mode='train')
    test_dataset = CSIDataset(data_path, rx_num=rx_num, mode='test')
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE, shuffle=False)
    
    # 动态导入服务器里的真实 CNN 模型架构
    from core.ai_engine import TwoStreamFallDetector
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_dir = os.path.join(project_root, "04_models")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = TwoStreamFallDetector(rx_num=rx_num, num_classes=4).to(device)
    
    save_path = os.path.join(model_dir, f"model_cnn_{rx_num}rx.pth")
        
    # 动态计算类别权重以解决数据不平衡问题
    train_labels = train_dataset.labels
    from collections import Counter
    label_counts = Counter(train_labels)
    total_samples = len(train_labels)
    
    class_weights = []
    for i in range(4): # 共有 4 个类别
        count = label_counts.get(i, 0)
        # 使用 inverse frequency 计算权重
        weight = total_samples / (4.0 * count) if count > 0 else 1.0
        class_weights.append(weight)
        
    class_weights_tensor = torch.FloatTensor(class_weights).to(device)
    print(f"\n[Info] 类别权重 (Class Weights): {class_weights_tensor.cpu().numpy()}")
    
    criterion = nn.CrossEntropyLoss(weight=class_weights_tensor)
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4) # 增加正则化防过拟合
    
    print("\n🚀 开始训练模型...")
    from tqdm import tqdm
    
    best_accuracy = 0.0
    patience = 15
    patience_counter = 0
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # 外层进度条用于估算总时间
    epoch_iterator = tqdm(range(EPOCHS), desc="Total Training Progress")
    
    for epoch in epoch_iterator:
        model.train()
        running_loss = 0.0
        
        # 内层进度条不再留存，避免刷屏
        batch_iterator = tqdm(train_loader, desc=f"Epoch [{epoch+1}/{EPOCHS}]", leave=False)
        for seqs, feats, labels in batch_iterator:
            seqs, feats, labels = seqs.to(device), feats.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(seqs, feats)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            
            # 实时更新内层进度条上的 Loss 显示
            batch_iterator.set_postfix(loss=f"{loss.item():.4f}")
            
        avg_train_loss = running_loss / len(train_loader)
        
        # 在验证集上跑一遍测试准确率
        model.eval()
        correct = 0
        total = 0
        val_loss = 0.0
        with torch.no_grad():
            for seqs, feats, labels in test_loader:
                seqs, feats, labels = seqs.to(device), feats.to(device), labels.to(device)
                outputs = model(seqs, feats)
                loss = criterion(outputs, labels)
                val_loss += loss.item()
                
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                
        accuracy = 100 * correct / total
        avg_val_loss = val_loss / len(test_loader)
        
        # 更新外层进度条的显示信息
        epoch_iterator.set_postfix(TrainLoss=f"{avg_train_loss:.4f}", ValLoss=f"{avg_val_loss:.4f}", Acc=f"{accuracy:.2f}%")
        
        # 模型收敛判断与早停 (Early Stopping)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            patience_counter = 0
            # 只有在准确率提升时才保存模型
            torch.save(model.state_dict(), save_path)
        else:
            patience_counter += 1
            
        if patience_counter >= patience:
            print(f"\n⚠️ 触发早停机制 (Early Stopping)：连续 {patience} 个 Epoch 验证集准确率未提升。模型已收敛！")
            break
            
    print("\n✅ 训练与测试流程结束！")
    print(f"🎯 模型在总体验证集上的最高准确率: {best_accuracy:.2f}%")
    print(f"💾 最优模型权重已保存至: {save_path}")
    
    # ---------------------------------------------------------
    # 最终详细报告：加载最优模型，输出各个类别的精准度 (Per-class Accuracy)
    # ---------------------------------------------------------
    print("\n📊 正在生成最优模型的各类别详细识别率报告 (Per-class Accuracy)...")
    try:
        model.load_state_dict(torch.load(save_path, weights_only=True))
        model.eval()
        
        class_correct = [0] * 4
        class_total = [0] * 4
        class_names = ["Empty (无人)", "Sitting (静坐)", "Walk (走动)", "Fall (跌倒)"]
        
        with torch.no_grad():
            for seqs, feats, labels in test_loader:
                seqs, feats, labels = seqs.to(device), feats.to(device), labels.to(device)
                outputs = model(seqs, feats)
                _, predicted = torch.max(outputs.data, 1)
                
                # 对于 batch size 为 1 的特殊情况处理
                c = (predicted == labels).squeeze()
                if c.dim() == 0:
                    c = c.unsqueeze(0)
                    
                for i in range(len(labels)):
                    lbl = labels[i].item()
                    class_correct[lbl] += c[i].item()
                    class_total[lbl] += 1
                    
        print("-" * 50)
        for i in range(4):
            if class_total[i] > 0:
                acc = 100 * class_correct[i] / class_total[i]
                print(f" 🔹 {class_names[i]:<18} 成功率: {acc:>6.2f}%  (命中: {class_correct[i]}/{class_total[i]})")
            else:
                print(f" 🔹 {class_names[i]:<18} 成功率:  N/A    (验证集中无此动作样本)")
        print("-" * 50)
        print("💡 提示：如果某个关键动作(如跌倒)成功率偏低，请使用数据收集脚本专项多录制几遍该动作。")
        
    except Exception as e:
        print(f"⚠️ 生成分类报告时出错: {e}")

if __name__ == "__main__":
    import time
    start_time = time.time()
    
    parser = argparse.ArgumentParser(description="训练边缘端 CNN 模型")
    parser.add_argument("--data", type=str, default="dataset", help="输入数据集路径 (可以是个文件夹或单个 CSV)")
    parser.add_argument("--rx", type=int, choices=[1, 2, 3], default=3, help="接收天线数量")
    args = parser.parse_args()
    
    train(args.data, args.rx)
    
    total_time = time.time() - start_time
    mins, secs = divmod(total_time, 60)
    print(f"\n⏱️ 脚本总运行时间: {int(mins)} 分 {int(secs)} 秒")
