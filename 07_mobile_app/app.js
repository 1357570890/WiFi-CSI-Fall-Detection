App({
  onLaunch() {
    console.log('App Launch');
  },
  globalData: {
    // 默认指向本机的 8000 端口。
    // 如果您要在真实的手机上预览（而不是在电脑的模拟器），请一定要把 127.0.0.1 换成您电脑连 WiFi 后的局域网 IP (例如 192.168.1.100)
    wsUrl: "ws://127.0.0.1:8000/ws" 
  }
})
