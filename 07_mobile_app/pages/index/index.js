const app = getApp()

Page({
  data: {
    currentTab: 'monitor', // 控制当前显示哪个 Tab
    isConnected: false,
    currentStatus: "等待 1~3Rx 接入...",
    statusCode: -1,
    logs: [],
    wsUrl: app.globalData.wsUrl,
    vibrateEnabled: true,
    autoReconnect: true,
    reconnectInterval: 3
  },

  socketTask: null,

  onLoad() {
    this.connectWebsocket();
  },

  // 炫酷底部导航栏切换逻辑
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    // 添加极短的震动反馈，增加高级感
    wx.vibrateShort({ type: 'light' }); 
    this.setData({ currentTab: tab });
  },

  onUrlInput(e) {
    this.setData({ wsUrl: e.detail.value });
  },

  onVibrateChange(e) {
    this.setData({ vibrateEnabled: e.detail.value });
  },

  onAutoReconnectChange(e) {
    this.setData({ autoReconnect: e.detail.value });
  },

  onIntervalInput(e) {
    let val = parseInt(e.detail.value);
    if (isNaN(val) || val <= 0) val = 3;
    this.setData({ reconnectInterval: val });
  },

  // 修改 IP 后重新连接
  reconnect() {
    wx.vibrateShort({ type: 'medium' });
    if (this.socketTask) {
      this.socketTask.close();
    }
    app.globalData.wsUrl = this.data.wsUrl;
    this.setData({ logs: [], currentStatus: "重连中...", statusCode: -1 });
    this.connectWebsocket();
    // 自动切回监护页
    this.setData({ currentTab: 'monitor' });
  },


  connectWebsocket() {
    const that = this;
    
    this.setData({ 
      isConnected: false,
      currentStatus: "正在连接...",
      statusCode: -1
    });

    this.socketTask = wx.connectSocket({
      url: this.data.wsUrl,
      success() {
        console.log('WebSocket 连接创建成功');
      }
    });

    this.socketTask.onOpen(() => {
      that.setData({ isConnected: true });
      that.addLog("✔️ 系统握手成功，动态感知矩阵上线");
    });

    this.socketTask.onClose(() => {
      that.setData({ isConnected: false });
      that.addLog(`⚠️ [物理层警告] 连接丢失，节点强制离线，切入休眠`);
      if (that.data.autoReconnect) {
        setTimeout(() => {
          that.connectWebsocket();
        }, that.data.reconnectInterval * 1000);
      }
    });

    this.socketTask.onError((err) => {
      that.addLog(`连接错误: ${err.errMsg}`);
    });

    this.socketTask.onMessage((res) => {
      try {
        let data = JSON.parse(res.data);
        
        if (that.data.statusCode !== data.status_code) {
            that.addLog(`多节点融合判定更新: ${data.status}`);
            
            if (data.status_code === 3) {
              if (that.data.vibrateEnabled) wx.vibrateLong(); 
              that.addLog(`🚨 联合验证确认：发生严重跌倒！`);
            }
            else if (data.status_code === 1) {
              that.addLog(`💤 目标进入静息态，系统自动切换至微波探测模式。`);
            }
        }

        that.setData({
          currentStatus: data.status,
          statusCode: data.status_code
        });

      } catch (e) {
        console.error("解析流式数据失败", e);
      }
    });
  },

  addLog(msg) {
    const d = new Date();
    const timeStr = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}.${d.getMilliseconds().toString().padStart(3, '0')}`;
    
    const newLogs = this.data.logs;
    newLogs.unshift({ time: timeStr, msg: msg });
    if (newLogs.length > 20) newLogs.pop();
    
    this.setData({ logs: newLogs });
  },

  onUnload() {
    if (this.socketTask) {
      this.socketTask.close();
    }
  }
})
