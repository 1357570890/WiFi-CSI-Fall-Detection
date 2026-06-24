<template>
  <view class="container">
    <view class="header">
      <text class="title">适老感知远程监控</text>
      <text class="status-dot" :class="isConnected ? 'online' : 'offline'"></text>
    </view>
    
    <view class="status-card" :class="'bg-' + statusCode">
      <text class="status-text">{{ currentStatus }}</text>
      <text v-if="statusCode === 2" class="alert-text">⚠️ 紧急报警</text>
    </view>

    <button @click="connectServer">重新连接网关</button>
  </view>
</template>

<script>
export default {
  data() {
    return {
      isConnected: false,
      currentStatus: '等待数据...',
      statusCode: 0
    }
  },
  onLoad() {
    this.connectServer();
  },
  methods: {
    connectServer() {
      // 替换为您 Windows 电脑的局域网 IP
      const socketTask = uni.connectSocket({
        url: 'ws://192.168.1.100:8000/ws',
        success: () => { console.log('WebSocket 连接成功'); }
      });
      
      uni.onSocketOpen(() => {
        this.isConnected = true;
      });
      
      uni.onSocketMessage((res) => {
        const data = JSON.parse(res.data);
        this.currentStatus = data.status;
        this.statusCode = data.status_code;
        
        if(this.statusCode === 2) {
          uni.vibrateLong(); // 跌倒时手机震动报警
        }
      });
      
      uni.onSocketError(() => { this.isConnected = false; });
      uni.onSocketClose(() => { this.isConnected = false; });
    }
  }
}
</script>

<style>
.container { padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
.title { font-size: 24px; font-weight: bold; }
.status-dot { width: 15px; height: 15px; border-radius: 50%; }
.online { background-color: #4CAF50; }
.offline { background-color: #F44336; }
.status-card { padding: 40px; border-radius: 12px; text-align: center; margin-bottom: 20px; color: white; }
.bg-0 { background-color: #4CAF50; }
.bg-1 { background-color: #2196F3; }
.bg-2 { background-color: #F44336; animation: blink 1s infinite; }
.status-text { font-size: 28px; font-weight: bold; }
.alert-text { display: block; margin-top: 15px; font-size: 20px; font-weight: bold; }
@keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.8; } 100% { opacity: 1; } }
</style>
