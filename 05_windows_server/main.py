import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from api.router import router as api_router
from core.udp_receiver import start_udp_server

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 后台启动 UDP 接收服务
    asyncio.create_task(start_udp_server())
    print("Windows CSI Server is fully running.")
    yield

app = FastAPI(title="Wi-Fi CSI Windows Server", lifespan=lifespan)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 和 WebSocket 路由
app.include_router(api_router)

# 挂载前端静态页面 (解决浏览器直接打开 html 导致的本地跨域/安全问题)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "06_frontend_dashboard")
app.mount("/dashboard", StaticFiles(directory=frontend_dir), name="dashboard")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
