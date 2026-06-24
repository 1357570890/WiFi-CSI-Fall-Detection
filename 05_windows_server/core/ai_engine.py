import numpy as np
import torch
import torch.nn as nn
import os

# ========================================================
# 支持 1Rx, 2Rx, 3Rx 的多维多模型自适应网络架构
# ========================================================

class ResidualBlock1D(nn.Module):
    def __init__(self, channels):
        super(ResidualBlock1D, self).__init__()
        self.conv1 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.conv2 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        
    def forward(self, x):
        residual = x
        out = self.conv1(x)
        out = self.relu(out)
        out = self.conv2(out)
        out += residual
        out = self.relu(out)
        return out

class SelfAttention(nn.Module):
    def __init__(self, hidden_size):
        super(SelfAttention, self).__init__()
        self.attention = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.Tanh(),
            nn.Linear(hidden_size // 2, 1)
        )
        
    def forward(self, x):
        # x shape: (batch_size, seq_len, hidden_size)
        weights = self.attention(x) # (batch_size, seq_len, 1)
        weights = torch.softmax(weights, dim=1)
        context = torch.sum(weights * x, dim=1) # (batch_size, hidden_size)
        return context

class TwoStreamFallDetector(nn.Module):
    def __init__(self, rx_num=1, num_classes=4):
        super(TwoStreamFallDetector, self).__init__()
        
        # 1. 时间主干流 (Temporal Stream): 深度 CNN (ResNet1D) + Bi-LSTM + Self-Attention
        self.cnn = nn.Sequential(
            nn.Conv1d(in_channels=rx_num * 11, out_channels=32, kernel_size=5, padding=2),
            nn.ReLU(),
            ResidualBlock1D(32),
            nn.MaxPool1d(kernel_size=2), # -> (batch, 32, 50)
            ResidualBlock1D(32)
        )
        
        self.lstm = nn.LSTM(input_size=32, hidden_size=64, num_layers=1, batch_first=True, bidirectional=True)
        # Bi-LSTM hidden state will be 64*2 = 128 dim
        self.attention = SelfAttention(128)
        
        # 2. 能量辅助流 (Energy Stream): MLP
        self.energy_mlp = nn.Sequential(
            nn.Linear(10 * rx_num, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU()
        )
        
        # 3. 特征融合层 (Fusion)
        self.classifier = nn.Sequential(
            nn.Linear(128 + 16, 64),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(64, num_classes)
        )
        
    def forward(self, seq, feats):
        # seq shape: (batch_size, rx_num, 100)
        # feats shape: (batch_size, 10 * rx_num)
        
        # Stream 1
        c_out = self.cnn(seq) # (batch_size, 32, 50)
        c_out = c_out.permute(0, 2, 1) # (batch_size, 50, 32)
        lstm_out, _ = self.lstm(c_out) # (batch_size, 50, 128)
        
        # Use Self-Attention instead of just taking the last hidden state
        h_temporal = self.attention(lstm_out) # (batch_size, 128)
        
        # Stream 2
        h_energy = self.energy_mlp(feats) # (batch_size, 16)
        
        # Fusion
        fused = torch.cat((h_temporal, h_energy), dim=1) # (batch_size, 144)
        return self.classifier(fused)

class FallDetectionModel:
    def __init__(self, base_model_dir="04_models"):
        self.classes = ["无人环境/离家", "原地静坐", "日常活动", "危险！跌倒异常"]
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.model_dir = os.path.join(project_root, base_model_dir)
        
        # 预先实例化模型并存储
import numpy as np
import torch
import torch.nn as nn
import os

# ========================================================
# 支持 1Rx, 2Rx, 3Rx 的多维多模型自适应网络架构
# ========================================================

class ResidualBlock1D(nn.Module):
    def __init__(self, channels):
        super(ResidualBlock1D, self).__init__()
        self.conv1 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.conv2 = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        
    def forward(self, x):
        residual = x
        out = self.conv1(x)
        out = self.relu(out)
        out = self.conv2(out)
        out += residual
        out = self.relu(out)
        return out

class SelfAttention(nn.Module):
    def __init__(self, hidden_size):
        super(SelfAttention, self).__init__()
        self.attention = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.Tanh(),
            nn.Linear(hidden_size // 2, 1)
        )
        
    def forward(self, x):
        # x shape: (batch_size, seq_len, hidden_size)
        weights = self.attention(x) # (batch_size, seq_len, 1)
        weights = torch.softmax(weights, dim=1)
        context = torch.sum(weights * x, dim=1) # (batch_size, hidden_size)
        return context

class TwoStreamFallDetector(nn.Module):
    def __init__(self, rx_num=1, num_classes=4):
        super(TwoStreamFallDetector, self).__init__()
        
        # 1. 时间主干流 (Temporal Stream): 深度 CNN (ResNet1D) + Bi-LSTM + Self-Attention
        # 每一个 rx 有 11 个子载波通道 (经过商谱降维 12 -> 11)
        self.cnn = nn.Sequential(
            nn.Conv1d(in_channels=rx_num * 11, out_channels=32, kernel_size=5, padding=2),
            nn.ReLU(),
            ResidualBlock1D(32),
            nn.MaxPool1d(kernel_size=2), # -> (batch, 32, 50)
            ResidualBlock1D(32)
        )
        
        self.lstm = nn.LSTM(input_size=32, hidden_size=64, num_layers=1, batch_first=True, bidirectional=True)
        # Bi-LSTM hidden state will be 64*2 = 128 dim
        self.attention = SelfAttention(128)
        
        # 2. 能量辅助流 (Energy Stream): MLP
        # 特征数量从 9 变为了 10 (增加了 CV)
        self.energy_mlp = nn.Sequential(
            nn.Linear(10 * rx_num, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU()
        )
        
        # 3. 特征融合层 (Fusion)
        self.classifier = nn.Sequential(
            nn.Linear(128 + 16, 64),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(64, num_classes)
        )
        
    def forward(self, seq, feats):
        # seq shape: (batch_size, rx_num, 100)
        # feats shape: (batch_size, 10 * rx_num)
        
        # Stream 1
        c_out = self.cnn(seq) # (batch_size, 32, 50)
        c_out = c_out.permute(0, 2, 1) # (batch_size, 50, 32)
        lstm_out, _ = self.lstm(c_out) # (batch_size, 50, 128)
        
        # Use Self-Attention instead of just taking the last hidden state
        h_temporal = self.attention(lstm_out) # (batch_size, 128)
        
        # Stream 2
        h_energy = self.energy_mlp(feats) # (batch_size, 16)
        
        # Fusion
        fused = torch.cat((h_temporal, h_energy), dim=1) # (batch_size, 144)
        return self.classifier(fused)

class FallDetectionModel:
    def __init__(self, base_model_dir="04_models"):
        self.classes = ["无人环境/离家", "原地静坐", "日常活动", "危险！跌倒异常"]
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.model_dir = os.path.join(project_root, base_model_dir)
        
        # 预先实例化模型并存储
        self.models = {
            1: {'net': TwoStreamFallDetector(rx_num=1).to(self.device), 'loaded': False, 'path': 'model_cnn_1rx.pth'},
            2: {'net': TwoStreamFallDetector(rx_num=2).to(self.device), 'loaded': False, 'path': 'model_cnn_2rx.pth'},
            3: {'net': TwoStreamFallDetector(rx_num=3).to(self.device), 'loaded': False, 'path': 'model_cnn_3rx.pth'},
        }
        
        # 尝试加载各自的权重
        for rx_num, model_info in self.models.items():
            abs_path = os.path.join(self.model_dir, model_info['path'])
            rel_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), base_model_dir, model_info['path'])
            
            target_path = abs_path if os.path.exists(abs_path) else rel_path
            
            if os.path.exists(target_path):
                try:
                    model_info['net'].load_state_dict(torch.load(target_path, map_location=self.device, weights_only=True))
                    model_info['net'].eval()
                    model_info['loaded'] = True
                    print(f"[AI Engine] {rx_num}Rx 融合模型加载成功: {target_path}")
                except Exception as e:
                    print(f"[AI Engine] {rx_num}Rx 模型加载失败: {e}")
            else:
                print(f"[AI Engine] {rx_num}Rx 模型权重文件未找到: {abs_path}")

    def predict(self, waveforms_matrix, feature_matrix):
        """
        接收波形矩阵 (rx_num * 11, 100) 和特征矩阵 (rx_num, 10)
        """
        waveforms_matrix = np.array(waveforms_matrix)
        feature_matrix = np.array(feature_matrix)
        
        if len(feature_matrix.shape) == 1:
            # 1Rx fallback if passed a 1D array
            rx_num = 1
        else:
            rx_num = feature_matrix.shape[0]
            
        # Flatten across antennas: (rx_num, 10) -> (rx_num * 10,)
        flattened_features = feature_matrix.flatten()
            
        if rx_num not in self.models:
            return 0, f"天线数量错误({rx_num})", 0.0
            
        model_info = self.models[rx_num]

        if not model_info['loaded']:
            return 0, "模型未加载", 0.0

        try:
            # waveforms_matrix shape is (rx_num * 11, 100)
            seq_tensor = torch.tensor(waveforms_matrix, dtype=torch.float32).unsqueeze(0).to(self.device)
            feats_tensor = torch.tensor(flattened_features, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                output = model_info['net'](seq_tensor, feats_tensor)
                probs = torch.nn.functional.softmax(output, dim=1).cpu().numpy()[0]
                pred_idx = np.argmax(probs)
                confidence = float(probs[pred_idx])
                
                # 触发大模型告警
                if pred_idx == 3:
                    from core.llm_notifier import llm_notifier
                    llm_notifier.trigger_fall_alert(confidence=confidence)
                    
                return int(pred_idx), self.classes[pred_idx], confidence
        except Exception as e:
            print(f"[AI Engine] {rx_num}Rx 推理出错: {e}")
            return 0, "推理错误", 0.0
