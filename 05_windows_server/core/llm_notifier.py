import threading
import time
import requests

class LLMNotifier:
    def __init__(self):
        self.last_alert_time = 0
        self.alert_cooldown = 10  # 10秒冷却期，防止狂发通知

    def trigger_fall_alert(self, confidence=0.0, max_amp=0.0):
        """非阻塞地触发告警"""
        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            return
        
        self.last_alert_time = current_time
        threading.Thread(target=self._fixed_alert, args=(confidence, max_amp), daemon=True).start()

    def _fixed_alert(self, confidence, max_amp):
        pass

llm_notifier = LLMNotifier()
