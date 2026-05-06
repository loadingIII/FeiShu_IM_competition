"""
飞书长连接管理器
用于在 FastAPI 应用中管理飞书 WebSocket 长连接
"""
import os
import json
import asyncio
import threading
from typing import Callable, Optional, Any
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger, P2CardActionTriggerResponse

from utils.logger_handler import logger
from app.service.feishu_message_service import feishu_message_service


class FeishuWSManager:
    """飞书 WebSocket 长连接管理器（支持在 FastAPI 中后台运行）"""

    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.client: Optional[lark.ws.Client] = None
        self.event_handler: Optional[lark.EventDispatcherHandler] = None
        self._message_callback: Optional[Callable] = None
        self._card_callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.bot_open_id: str = ""

    def set_message_callback(self, callback: Callable):
        """设置消息接收回调函数

        Args:
            callback: 异步回调函数，接收参数 (chat_id, sender_open_id, message_text)
        """
        self._message_callback = callback

    def set_card_callback(self, callback: Callable):
        """设置卡片交互回调函数

        Args:
            callback: 异步回调函数，接收参数 (workflow_id, action, feedback)
        """
        self._card_callback = callback

    def _on_p2_im_message_receive_v1(self, data: P2ImMessageReceiveV1) -> None:
        """处理接收消息事件 (v2.0)"""
        try:
            event = data.event
            if not event:
                logger.warning("[FeishuWS] 消息事件为空")
                return

            message = event.message
            sender = event.sender

            if not message or not sender:
                logger.warning(f"[FeishuWS] 消息或发送者为空: message={message}, sender={sender}")
                return

            msg_type = message.message_type
            chat_id = message.chat_id
            sender_open_id = sender.sender_id.open_id if sender.sender_id else None

            logger.info(f"[FeishuWS] 收到消息事件: msg_type={msg_type}, chat_id={chat_id}, sender={sender_open_id}")

            # 只处理文本消息
            if msg_type == "text" and message.content:
                try:
                    content = json.loads(message.content)
                    text = content.get("text", "").strip()
                    logger.info(f"[FeishuWS] 解析消息内容: text={text[:50]}...")

                    # 过滤掉 @ 机器人的部分（群聊中 @ 机器人会包含在消息中）
                    # 飞书 @ 用户的格式是 <at id="user_id">@用户名</at>
                    import re
                    text = re.sub(r'<at[^>]*>[^<]*</at>', '', text).strip()
                    logger.info(f"[FeishuWS] 过滤 @ 后的消息: text={text[:50]}...")

                    if text:
                        # --- chat_type routing ---
                        chat_type = message.chat_type

                        if chat_type == "group":
                            mentions = message.mentions or []
                            is_mentioned = any(
                                getattr(m, 'id', None) and getattr(m.id, 'open_id', None) == self.bot_open_id
                                for m in mentions
                            )

                            if not is_mentioned:
                                return
                        # --- END chat_type routing ---

                        logger.info(f"[FeishuWS] 准备处理消息 from {sender_open_id}: {text[:50]}...")
                        # 异步执行回调
                        if self._message_callback and self._loop:
                            asyncio.run_coroutine_threadsafe(
                                self._message_callback(chat_id, sender_open_id, text),
                                self._loop
                            )
                            logger.info(f"[FeishuWS] 消息已提交到回调处理")
                        else:
                            logger.warning(f"[FeishuWS] 回调函数或事件循环未设置: callback={self._message_callback}, loop={self._loop}")
                except json.JSONDecodeError as e:
                    logger.warning(f"[FeishuWS] 消息内容解析失败: {message.content}, error={e}")
            else:
                logger.info(f"[FeishuWS] 非文本消息或内容为空: msg_type={msg_type}, has_content={bool(message.content)}")

        except Exception as e:
            logger.error(f"[FeishuWS] 处理消息事件失败: {e}", exc_info=True)

    def _on_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self, data) -> None:
        """处理用户进入机器人单聊事件
        
        注意：这个事件在用户第一次进入机器人单聊时触发
        """
        try:
            logger.info(f"[FeishuWS] 用户进入机器人单聊事件: {type(data)}")
            
            # 尝试不同的方式获取事件数据
            event = None
            if hasattr(data, 'event'):
                event = data.event
            elif hasattr(data, 'json'):
                event = json.loads(data.json()).get('event', {})
            
            if event:
                chat_id = getattr(event, 'chat_id', None)
                user_id = None
                if hasattr(event, 'user_id') and event.user_id:
                    user_id = getattr(event.user_id, 'open_id', None)
                
                logger.info(f"[FeishuWS] 用户进入机器人单聊: user_id={user_id}, chat_id={chat_id}")
            else:
                logger.info(f"[FeishuWS] 收到 bot_p2p_chat_entered 事件，但无法解析事件数据")

        except Exception as e:
            logger.error(f"[FeishuWS] 处理用户进入单聊事件失败: {e}", exc_info=True)

    def _on_card_action_trigger(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """处理卡片交互事件 (v2.0)

        流程:
        1. 解析卡片事件，提取 action、workflow_id、feedback
        2. 验证输入数据完整性和安全性
        3. 调用后端回调处理确认/修改/取消逻辑
        4. 返回 Toast 反馈给用户
        """
        try:
            event = data.event
            if not event:
                logger.warning("[FeishuWS] 卡片事件为空")
                return self._build_error_response("处理失败，请稍后重试")

            action = event.action
            if not action:
                logger.warning("[FeishuWS] 卡片操作数据为空")
                return self._build_error_response("处理失败，请稍后重试")

            action_value = action.value if hasattr(action, "value") and action.value else {}
            action_name = action.name if hasattr(action, "name") else ""
            form_value = action.form_value if hasattr(action, "form_value") and isinstance(action.form_value, dict) else {}
            feedback = form_value.get("modify_content", "") if isinstance(form_value, dict) else ""
            feedback = feedback.strip() if isinstance(feedback, str) else ""

            action_type = action_value.get("action", "")
            workflow_id = action_value.get("workflow_id", "") or form_value.get("workflow_id", "")
            confirm_type = action_value.get("confirm_type", "") or form_value.get("confirm_type", "")

            # form submit 不携带按钮 value，通过按钮 name 判断操作类型
            if not action_type:
                if action_name == "confirm_btn":
                    action_type = "modify" if feedback else "confirm"
                elif action_name == "modify_btn":
                    action_type = "modify"
                elif action_name == "cancel_btn":
                    action_type = "cancel"

            # form submit 也不携带 workflow_id，通过 message_id 查找待确认上下文
            if not workflow_id:
                message_id = self._extract_message_id(event)
                pending = feishu_message_service.get_pending_confirmation_by_message_id(message_id)
                if pending:
                    workflow_id = pending.get("workflow_id", "")
                    confirm_type = pending.get("confirm_type", confirm_type)

            logger.info(
                f"[FeishuWS] 收到卡片交互: action={action_type}, action_name={action_name}, "
                f"workflow_id={workflow_id}, confirm_type={confirm_type}, "
                f"feedback_length={len(feedback)}"
            )

            if not workflow_id:
                return self._build_error_response("无法识别工作流，请刷新后重试")

            if not self._card_callback or not self._loop:
                return self._build_error_response("服务暂不可用，请稍后重试")

            # ---------- 确认操作 ----------
            if action_type == "confirm":
                logger.info(f"[FeishuWS] 开始执行确认回调: workflow_id={workflow_id}, loop={self._loop}")
                future = asyncio.run_coroutine_threadsafe(
                    self._card_callback(workflow_id, "confirm", ""),
                    self._loop
                )
                try:
                    future.result(timeout=10)
                    logger.info(f"[FeishuWS] 确认回调执行成功: workflow_id={workflow_id}")
                    feishu_message_service.clear_pending_confirmation(workflow_id)
                    return self._build_success_response("✅ 已确认，正在继续执行...")
                except Exception as e:
                    logger.error(f"[FeishuWS] 确认操作失败: {e}", exc_info=True)
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "confirm", confirm_type
                    )
                    return self._build_error_response(f"确认失败: {e}", card=card)

            # ---------- 取消操作 ----------
            elif action_type == "cancel":
                future = asyncio.run_coroutine_threadsafe(
                    self._card_callback(workflow_id, "cancel", ""),
                    self._loop
                )
                try:
                    future.result(timeout=10)
                    feishu_message_service.clear_pending_confirmation(workflow_id)
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "cancel", confirm_type
                    )
                    return self._build_success_response("❌ 已取消任务", card=card)
                except Exception as e:
                    logger.error(f"[FeishuWS] 取消操作失败: {e}")
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "cancel", confirm_type
                    )
                    return self._build_error_response(f"取消失败: {e}", card=card)

            # ---------- 修改操作 ----------
            elif action_type == "modify":
                # 1. 验证输入不为空
                if not feedback:
                    return self._build_warning_response("✏️ 请先在输入框填写修改内容，再点击【修改】")

                # 2. 验证输入长度
                if len(feedback) > 5000:
                    return self._build_warning_response("✏️ 修改内容不能超过 5000 个字符")

                # 3. 验证输入安全性（基础 XSS 检查）
                import re
                suspicious_patterns = [
                    (r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', "包含脚本标签"),
                    (r'javascript:', "包含 JavaScript 协议"),
                    (r'on\w+\s*=', "包含事件处理器"),
                ]
                for pattern, desc in suspicious_patterns:
                    if re.search(pattern, feedback, re.IGNORECASE):
                        return self._build_warning_response(f"✏️ 输入内容不安全: {desc}，请重新输入")

                # 4. 提交修改
                future = asyncio.run_coroutine_threadsafe(
                    self._card_callback(workflow_id, "modify", feedback),
                    self._loop
                )
                try:
                    future.result(timeout=10)
                    feishu_message_service.clear_pending_confirmation(workflow_id)
                    display_feedback = feedback[:50] + ("..." if len(feedback) > 50 else "")
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "modify", confirm_type, extra_info=feedback
                    )
                    return self._build_success_response(f"✏️ 已提交修改意见: {display_feedback}", card=card)
                except Exception as e:
                    logger.error(f"[FeishuWS] 修改操作失败: {e}")
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "modify", confirm_type
                    )
                    return self._build_error_response(f"修改失败: {e}", card=card)

            # ---------- 显示修改输入框 ----------
            elif action_type == "show_modify_input":
                if feedback:
                    future = asyncio.run_coroutine_threadsafe(
                        self._card_callback(workflow_id, "modify", feedback),
                        self._loop
                    )
                    try:
                        future.result(timeout=10)
                        feishu_message_service.clear_pending_confirmation(workflow_id)
                        display_feedback = feedback[:50] + ("..." if len(feedback) > 50 else "")
                        card = feishu_message_service.build_action_result_card(
                            workflow_id, "modify", confirm_type, extra_info=feedback
                        )
                        return self._build_success_response(f"✏️ 已提交修改意见: {display_feedback}", card=card)
                    except Exception as e:
                        logger.error(f"[FeishuWS] 修改操作失败: {e}")
                        card = feishu_message_service.build_action_result_card(
                            workflow_id, "modify", confirm_type
                        )
                        return self._build_error_response(f"修改失败: {e}", card=card)
                return self._build_warning_response("✏️ 请先在输入框填写修改内容，再点击【修改】提交")

            # ---------- 提交反馈（兼容旧卡片） ----------
            elif action_type == "submit_feedback":
                feedback = form_value.get("feedback", "") if isinstance(form_value, dict) else ""
                feedback = feedback.strip() if isinstance(feedback, str) else ""
                if not feedback:
                    return self._build_warning_response("✏️ 修改内容不能为空")

                future = asyncio.run_coroutine_threadsafe(
                    self._card_callback(workflow_id, "modify", feedback),
                    self._loop
                )
                try:
                    future.result(timeout=10)
                    feishu_message_service.clear_pending_confirmation(workflow_id)
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "modify", confirm_type, extra_info=feedback
                    )
                    return self._build_success_response(f"✏️ 已提交修改意见: {feedback[:50]}...", card=card)
                except Exception as e:
                    logger.error(f"[FeishuWS] 修改操作失败: {e}")
                    card = feishu_message_service.build_action_result_card(
                        workflow_id, "modify", confirm_type
                    )
                    return self._build_error_response(f"修改失败: {e}", card=card)

            return self._build_error_response("无效的操作请求")

        except Exception as e:
            logger.error(f"[FeishuWS] 处理卡片交互失败: {e}", exc_info=True)
            return self._build_error_response("处理失败，请稍后重试")

    def _extract_message_id(self, evt: Any) -> str:
        """从事件上下文提取消息ID（兼容不同SDK字段）"""
        # P2CardActionTrigger 的 context 在 evt.event.context 下
        event_data = getattr(evt, "event", None)
        context = getattr(event_data, "context", None) if event_data else None
        if not context:
            context = getattr(evt, "context", None)
        candidates = [
            getattr(context, "open_message_id", None) if context else None,
            getattr(context, "message_id", None) if context else None,
            getattr(evt, "open_message_id", None),
            getattr(evt, "message_id", None),
        ]
        for c in candidates:
            if c:
                return c
        return ""

    def _build_card_response(self, toast_message: str) -> dict:
        """构建卡片响应"""
        return {
            "toast": {
                "type": "success",
                "content": toast_message
            }
        }

    def _build_success_response(self, message: str, card: dict = None) -> P2CardActionTriggerResponse:
        """构建成功响应"""
        resp = {"toast": {"type": "success", "content": message}}
        if card:
            resp["card"] = card
        return P2CardActionTriggerResponse(resp)

    def _build_error_response(self, message: str, card: dict = None) -> P2CardActionTriggerResponse:
        """构建错误响应"""
        resp = {"toast": {"type": "error", "content": message}}
        if card:
            resp["card"] = card
        return P2CardActionTriggerResponse(resp)

    def _build_warning_response(self, message: str, card: dict = None) -> P2CardActionTriggerResponse:
        """构建警告响应"""
        resp = {"toast": {"type": "warning", "content": message}}
        if card:
            resp["card"] = card
        return P2CardActionTriggerResponse(resp)





    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        """构建事件处理器"""
        return self._build_event_handler_with_lark(lark)

    def _build_event_handler_with_lark(self, lark_module) -> lark.EventDispatcherHandler:
        """使用指定的 lark 模块构建事件处理器"""
        return (
            lark_module.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_p2_im_message_receive_v1)
            .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self._on_p2_im_chat_access_event_bot_p2p_chat_entered_v1)
            .register_p2_card_action_trigger(self._on_card_action_trigger)
            .build()
        )

    def _patch_ws_client_card_handling(self, ws_client_module):
        """猴子补丁：让 WS 客户端处理 CARD 类型消息（SDK 原生不支持）"""
        import base64
        import http
        from lark_oapi.core.json import JSON
        from lark_oapi.ws.model import Response
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger, P2CardActionTriggerResponse,
        )

        _original_handle_data_frame = ws_client_module.Client._handle_data_frame

        async def _patched_handle_data_frame(self_client, frame):
            hs = frame.headers
            type_header = None
            for h in hs:
                if h.key == "type":
                    type_header = h.value
                    break

            if type_header != "card":
                return await _original_handle_data_frame(self_client, frame)

            # 处理 CARD 消息
            msg_id = None
            trace_id = None
            sum_ = None
            seq = None
            for h in hs:
                if h.key == "message_id":
                    msg_id = h.value
                elif h.key == "trace_id":
                    trace_id = h.value
                elif h.key == "sum":
                    sum_ = h.value
                elif h.key == "seq":
                    seq = h.value

            pl = frame.payload
            if sum_ and int(sum_) > 1:
                pl = self_client._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            resp = Response(code=http.HTTPStatus.OK)
            try:
                start = int(round(__import__('time').time() * 1000))

                card_event = JSON.unmarshal(str(pl, "utf-8"), P2CardActionTrigger)
                logger.info(f"[FeishuWS] CARD 事件已解析，开始处理...")
                result = self._on_card_action_trigger(card_event)

                end = int(round(__import__('time').time() * 1000))
                header = hs.add()
                header.key = "bizRT"
                header.value = str(end - start)

                if result is not None:
                    resp_json = JSON.marshal(result)
                    resp.data = base64.b64encode(resp_json.encode("utf-8"))
                    logger.info(f"[FeishuWS] CARD 响应已生成，耗时 {end - start}ms, data={resp_json[:200]}")
                else:
                    logger.warning(f"[FeishuWS] CARD 处理返回 None")
            except Exception as e:
                logger.error(f"[FeishuWS] 处理 CARD 消息失败: {e}", exc_info=True)
                resp = Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = JSON.marshal(resp).encode("utf-8")
            await self_client._write_message(frame.SerializeToString())

        ws_client_module.Client._handle_data_frame = _patched_handle_data_frame
        logger.info("[FeishuWS] 已修补 WS 客户端，支持 CARD 消息处理")

    def _run_client(self):
        """在后台线程中运行客户端"""
        # 在新线程中创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 使用 nest_asyncio 来允许嵌套的事件循环
        try:
            import nest_asyncio
            nest_asyncio.apply()
            logger.info("[FeishuWS] 已应用 nest_asyncio")
        except ImportError:
            logger.warning("[FeishuWS] nest_asyncio 未安装，尝试直接启动")
        
        try:
            # 重新导入 lark_oapi.ws.client 模块以获取新的事件循环
            import importlib
            import lark_oapi.ws.client as ws_client_module
            importlib.reload(ws_client_module)
            
            # 重新导入 lark_oapi 以获取最新的事件处理器构建器
            import lark_oapi as lark_module
            importlib.reload(lark_module)
            
            # 在重新加载后构建事件处理器
            self.event_handler = self._build_event_handler_with_lark(lark_module)
            
            # 使用重新加载后的模块创建客户端
            self.client = ws_client_module.Client(
                self.app_id,
                self.app_secret,
                event_handler=self.event_handler,
                log_level=lark_module.LogLevel.INFO,
            )

            # 猴子补丁：让 WS 客户端处理 CARD 类型消息
            self._patch_ws_client_card_handling(ws_client_module)

            logger.info("[FeishuWS] 后台线程中启动长连接客户端...")
            self.client.start()
        except Exception as e:
            logger.error(f"[FeishuWS] 客户端异常: {e}", exc_info=True)
        finally:
            self._running = False
            # 清理事件循环
            try:
                loop.close()
            except Exception as e:
                logger.warning(f"[FeishuWS] 清理事件循环异常: {e}")

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """启动长连接客户端（在后台线程中运行）

        Args:
            loop: 主事件循环，用于回调
        """
        if not self.app_id or not self.app_secret:
            logger.error("[FeishuWS] FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量必须设置")
            return

        if self._running:
            logger.warning("[FeishuWS] 客户端已在运行中")
            return

        self._loop = loop
        self._running = True

        # 在后台线程中启动客户端
        self._thread = threading.Thread(target=self._run_client, daemon=True)
        self._thread.start()
        logger.info("[FeishuWS] 长连接客户端已在后台启动")

    def stop(self) -> None:
        """停止长连接客户端"""
        self._running = False
        # 注意：lark-oapi 的 ws client 没有显式 stop 方法
        # 线程会随着进程结束而终止
        logger.info("[FeishuWS] 长连接客户端停止信号已发送")


# 全局管理器实例
feishu_ws_manager = FeishuWSManager()
