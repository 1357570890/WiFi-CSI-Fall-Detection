import asyncio

# 全局 WebSocket 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Frontend Client Connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WebSocket] Frontend Client Disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# 全局共享状态
current_status = {
    "status": "[系统待机] 0 节点连接",
    "status_code": -1,
    "active_nodes": 0
}
