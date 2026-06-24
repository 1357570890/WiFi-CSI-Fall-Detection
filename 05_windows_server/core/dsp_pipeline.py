import numpy as np
from scipy.signal import butter, filtfilt

# 12 个抗干扰能力最强的子载波索引（规避 DC 与保护带）
VALID_SUBCARRIERS = [12, 14, 16, 18, 20, 24, 28, 36, 40, 44, 48, 52]

def hampel_filter(data_series, window_size=5, n_sigmas=3):
    """
    向量化实现的高效汉普尔滤波器 (Hampel Filter) 
    比纯 Python 循环提速约 50 倍以上
    """
    import pandas as pd
    s = pd.Series(data_series)
    # 计算滚动中位数和绝对中位差 (MAD)
    rolling_median = s.rolling(window=window_size*2, center=True, min_periods=1).median()
    rolling_mad = s.rolling(window=window_size*2, center=True, min_periods=1).apply(
        lambda x: np.median(np.abs(x - np.median(x))), raw=True
    )
    
    # 找到所有离群点
    outlier_idx = np.abs(s - rolling_median) > n_sigmas * rolling_mad
    
    # 替换离群点
    s[outlier_idx] = rolling_median[outlier_idx]
    
    return s.values

def butter_lowpass_filter(data, cutoff=11.0, fs=100.0, order=1, axis=-1):
    """
    巴特沃斯低通滤波器 (Butterworth Lowpass Filter)
    """
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    if data.shape[axis] <= max(len(a), len(b)) * 3:
        return data
    y = filtfilt(b, a, data, axis=axis)
    return y

def exponential_moving_average(data_series, alpha=0.15):
    """
    一维指数加权移动平均 (EMA) 平滑
    """
    ema = np.zeros_like(data_series)
    ema[0] = data_series[0]
    for t in range(1, len(data_series)):
        ema[t] = alpha * data_series[t] + (1 - alpha) * ema[t-1]
    return ema

def exponential_moving_average_2d(data_matrix, alpha=0.15):
    """
    二维指数加权移动平均 (沿时间轴)
    """
    ema = np.zeros_like(data_matrix)
    ema[0] = data_matrix[0]
    for t in range(1, len(data_matrix)):
        ema[t] = alpha * data_matrix[t] + (1 - alpha) * ema[t-1]
    return ema

def extract_features(x):
    """
    从平滑后的序列提取 10 维时域统计特征 (新增 CV 特征)
    """
    if len(x) < 2:
        return np.zeros(10)
        
    # 0. 均值
    turb_mean = np.mean(x)
    # 1. 标准差
    turb_std = np.std(x)
    # 2. 最大值
    turb_max = np.max(x)
    # 3. 最小值
    turb_min = np.min(x)
    # 4. 四分位距 (IQR)
    q75, q25 = np.percentile(x, [75, 25])
    turb_iqr = q75 - q25
    # 5. 偏度 (Skewness)
    if turb_std > 1e-6:
        turb_skewness = np.mean((x - turb_mean)**3) / (turb_std**3)
    else:
        turb_skewness = 0
    # 6. 自相关性 (Lag-1 Autocorrelation)
    if turb_std > 1e-6:
        turb_autocorr = np.mean((x[:-1] - turb_mean) * (x[1:] - turb_mean)) / (turb_std**2)
    else:
        turb_autocorr = 0
    # 7. 绝对中位差 (MAD)
    median_val = np.median(x)
    turb_mad = np.median(np.abs(x - median_val))
    # 8. 波形长度 (Waveform Length) - 总变异度
    waveform_length = np.sum(np.abs(np.diff(x)))
    # 9. 变异系数 (CV = STD / MEAN) - 对硬件 AGC 波动鲁棒
    if abs(turb_mean) > 1e-6:
        turb_cv = turb_std / abs(turb_mean)
    else:
        turb_cv = 0
    
    return np.array([
        turb_mean, turb_std, turb_max, turb_min, turb_iqr, 
        turb_skewness, turb_autocorr, turb_mad, waveform_length, turb_cv
    ])

def process_raw_csi_to_features(raw_csi_buffer):
    """
    # 时空特征管线：保留完整空间特征，输出 2D 特征图供 1D-CNN 提取高级语义信息
    """
    # 1. 过滤到黄金 12 子载波
    filtered_amps = raw_csi_buffer[:, VALID_SUBCARRIERS]
    
    # 2. 商谱降维 (消除设备AGC抖动)，shape -> (100, 11)
    eps = 1e-6
    ratios = filtered_amps[:, 1:] / (filtered_amps[:, :-1] + eps)
    
    # ==========================================
    # 分支 A：辅助分支 (用于画图、动态阈值计算和辅助 MLP)
    # ==========================================
    sequence = np.median(ratios, axis=1)
    clean_sequence = hampel_filter(sequence, window_size=5, n_sigmas=3)
    lp_sequence = butter_lowpass_filter(clean_sequence, cutoff=11.0, fs=100.0, order=1, axis=-1)
    smooth_sequence = exponential_moving_average(lp_sequence, alpha=0.15)
    features = extract_features(smooth_sequence)
    
    # ==========================================
    # 分支 B：主干时空分支 (送给深层 CNN 的二维特征图)
    # 保留完整的 11 个子载波通道
    # ==========================================
    # 在时间轴(axis=0)上进行逐子载波的平滑去噪
    clean_ratios = np.apply_along_axis(lambda x: hampel_filter(x, window_size=5, n_sigmas=3), 0, ratios)
    lp_ratios = butter_lowpass_filter(clean_ratios, cutoff=11.0, fs=100.0, order=1, axis=0)
    spatial_matrix = exponential_moving_average_2d(lp_ratios, alpha=0.15) # shape: (100, 11)
    
    # PyTorch 1D CNN 需要的通道格式是 (Channels, Seq_Length)，即 (11, 100)
    spatial_matrix = spatial_matrix.T
    
    # 返回三者：10维统计特征、11x100的二维特征矩阵、用于前端展示的1D平滑波形
    return features, spatial_matrix, smooth_sequence
