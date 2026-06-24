from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from core.global_state import manager, current_status

router = APIRouter()

@router.get("/")
def read_root():
    return RedirectResponse(url="/dashboard/index.html")

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # 发送初始状态
        await websocket.send_json(current_status)
        while True:
            # 保持连接，等待接收心跳或前端指令
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
