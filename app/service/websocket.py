"""WebSocket 连接管理器

管理所有前端 WebSocket 连接，提供广播方法向客户端推送实时状态。
"""
import json
import time
from typing import Set, Any, Dict
from fastapi import WebSocket
from utils.logger_handler import logger


class WebSocketManager:
    """管理 WebSocket 连接与消息广播"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._subscriptions: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"[WebSocket] 客户端连接，当前连接数: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket):
        self._connections.discard(websocket)
        for subs in self._subscriptions.values():
            subs.discard(websocket)
        logger.info(f"[WebSocket] 客户端断开，当前连接数: {len(self._connections)}")

    async def subscribe(self, websocket: WebSocket, workflow_id: str):
        if workflow_id not in self._subscriptions:
            self._subscriptions[workflow_id] = set()
        self._subscriptions[workflow_id].add(websocket)

    async def unsubscribe(self, websocket: WebSocket, workflow_id: str):
        subs = self._subscriptions.get(workflow_id)
        if subs:
            subs.discard(websocket)

    async def broadcast(self, message: dict):
        """向所有连接的客户端广播"""
        payload = json.dumps(message, ensure_ascii=False)
        stale = set()
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.add(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_to_workflow(self, workflow_id: str, message: dict):
        """向订阅了指定工作流的客户端广播"""
        payload = json.dumps(message, ensure_ascii=False)
        subs = self._subscriptions.get(workflow_id, set())
        stale = set()
        for ws in subs:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.add(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_workflow_created(self, workflow_id: str, data: dict):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "workflow_created",
            "data": data,
        })

    async def broadcast_scene_started(self, workflow_id: str, scene: str):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "scene_started",
            "workflowId": workflow_id,
            "scene": scene,
        })

    async def broadcast_scene_progress(self, workflow_id: str, scene: str,
                                       progress: int, message: str = ""):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "scene_progress",
            "workflowId": workflow_id,
            "scene": scene,
            "progress": progress,
            "message": message,
        })

    async def broadcast_scene_completed(self, workflow_id: str, scene: str,
                                        duration: int = 0):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "scene_completed",
            "workflowId": workflow_id,
            "scene": scene,
            "duration": duration,
        })

    async def broadcast_scene_failed(self, workflow_id: str, scene: str, error: str = ""):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "scene_failed",
            "workflowId": workflow_id,
            "scene": scene,
            "error": error,
        })

    async def broadcast_confirm_required(self, workflow_id: str, confirm_type: str, content: Any):
        """广播确认请求，将后端 confirm_type 映射为前端可识别的类型"""
        confirm_type_map = {
            "task_plan": "plan",
            "doc_outline": "outline",
            "ppt_outline": "outline",
            "ppt_content": "outline",
        }
        mapped_type = confirm_type_map.get(confirm_type, "outline")
        await self.broadcast_to_workflow(workflow_id, {
            "type": "confirm_required",
            "workflowId": workflow_id,
            "confirmType": mapped_type,
            "content": content,
        })

    async def broadcast_confirm_result(self, workflow_id: str, action: str):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "confirm_result",
            "workflowId": workflow_id,
            "action": action,
        })

    async def broadcast_workflow_completed(self, workflow_id: str, delivery: Any = None):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "workflow_completed",
            "workflowId": workflow_id,
            "delivery": delivery,
        })

    async def broadcast_workflow_failed(self, workflow_id: str, error: str):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "workflow_failed",
            "workflowId": workflow_id,
            "error": error,
        })

    async def broadcast_workflow_cancelled(self, workflow_id: str):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "workflow_cancelled",
            "workflowId": workflow_id,
        })

    async def broadcast_log(self, workflow_id: str, level: str, message: str):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "log",
            "workflowId": workflow_id,
            "log": {
                "id": f"log_{int(time.time() * 1000)}_{hash(message) % 10000}",
                "timestamp": int(time.time() * 1000),
                "level": level,
                "message": message,
            },
        })

    async def broadcast_chat_message(self, workflow_id: str, msg_data: dict):
        await self.broadcast_to_workflow(workflow_id, {
            "type": "chat_message",
            "workflowId": workflow_id,
            "message": msg_data,
        })


ws_manager = WebSocketManager()
