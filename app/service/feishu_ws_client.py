"""
飞书长连接客户端
使用 WebSocket 与飞书开放平台建立长连接，接收事件消息
"""
import os
import json
import asyncio
from typing import Callable, Optional
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from utils.logger_handler import logger


class FeishuWSClient:
    """飞书 WebSocket 长连接客户端"""

    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.client: Optional[lark.ws.Client] = None
        self.event_handler: Optional[lark.EventDispatcherHandler] = None
        self._message_callback: Optional[Callable] = None
        self._running = False

    def set_message_callback(self, callback: Callable):
        """设置消息接收回调函数

        Args:
            callback: 回调函数，接收参数 (chat_id, sender_open_id, message_text)
        """
        self._message_callback = callback

    def _on_p2_im_message_receive_v1(self, data: P2ImMessageReceiveV1) -> None:
        """处理接收消息事件 (v2.0)"""
        try:
            event = data.event
            if not event:
                return

            message = event.message
            sender = event.sender

            if not message or not sender:
                return

            msg_type = message.message_type
            chat_id = message.chat_id
            sender_open_id = sender.sender_id.open_id if sender.sender_id else None

            # 只处理文本消息
            if msg_type == "text" and message.content:
                try:
                    content = json.loads(message.content)
                    text = content.get("text", "").strip()
                    if text:
                        logger.info(f"[FeishuWS] 收到消息 from {sender_open_id}: {text}")
                        # 异步执行回调
                        if self._message_callback:
                            asyncio.create_task(
                                self._message_callback(chat_id, sender_open_id, text)
                            )
                except json.JSONDecodeError:
                    logger.warning(f"[FeishuWS] 消息内容解析失败: {message.content}")

        except Exception as e:
            logger.error(f"[FeishuWS] 处理消息事件失败: {e}")

    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        """构建事件处理器"""
        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_p2_im_message_receive_v1)
            .build()
        )

    def start(self) -> None:
        """启动长连接客户端（阻塞方法）"""
        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量必须设置")

        if self._running:
            logger.warning("[FeishuWS] 客户端已在运行中")
            return

        self.event_handler = self._build_event_handler()
        self.client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=self.event_handler,
            log_level=lark.LogLevel.INFO,
        )

        self._running = True
        logger.info("[FeishuWS] 正在启动长连接客户端...")

        try:
            # 启动客户端（阻塞）
            self.client.start()
        except KeyboardInterrupt:
            logger.info("[FeishuWS] 收到中断信号，正在停止...")
        except Exception as e:
            logger.error(f"[FeishuWS] 客户端异常: {e}")
        finally:
            self._running = False
            logger.info("[FeishuWS] 客户端已停止")

    def start_async(self) -> asyncio.Task:
        """在异步环境中启动长连接客户端（非阻塞）

        Returns:
            asyncio.Task: 客户端任务
        """
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, self.start)

    def stop(self) -> None:
        """停止长连接客户端"""
        if self.client:
            # lark-oapi 的 ws client 没有显式 stop 方法
            # 需要通过其他方式停止，如发送信号或关闭进程
            logger.info("[FeishuWS] 停止客户端（请通过 Ctrl+C 或终止进程来停止）")
        self._running = False


# 全局客户端实例
feishu_ws_client = FeishuWSClient()
