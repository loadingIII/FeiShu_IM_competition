"""
飞书消息服务
处理工作流与飞书机器人的消息交互，包括：
- 发送工作流结果到飞书
- 发送确认卡片到飞书
- 处理卡片回调
"""
import json
import asyncio
import os
from typing import Optional, Dict, Any
from datetime import datetime

from utils.feishuUtils import feishu_api
from utils.logger_handler import logger


class FeishuMessageService:
    """飞书消息服务"""

    def __init__(self):
        # key: workflow_id
        # value: {workflow_id, confirm_type, chat_id, message_id}
        self._pending_confirmations: Dict[str, Dict[str, Any]] = {}

    async def send_workflow_result(
        self,
        chat_id: str,
        workflow_id: str,
        result: Dict[str, Any],
    ) -> bool:
        """发送工作流执行结果到飞书

        Args:
            chat_id: 飞书会话 ID
            workflow_id: 工作流 ID
            result: 工作流结果数据
        Returns:
            bool: 是否发送成功
        """
        try:
            ppt_uploaded = False

            # 先上传PPT文件（如果存在），获取结果用于卡片展示
            ppt_url = result.get("ppt_url", "")
            if ppt_url and not ppt_url.startswith("mock://"):
                try:
                    file_name = os.path.basename(ppt_url)
                    file_key = await feishu_api.upload_im_file(
                        file_path=ppt_url,
                        file_name=file_name,
                    )
                    await feishu_api.send_file_message(
                        receive_id=chat_id,
                        file_key=file_key,
                        receive_id_type="chat_id",
                    )
                    ppt_uploaded = True
                    logger.info(f"[FeishuMsg] PPT文件消息已发送: {workflow_id}")
                except Exception as file_err:
                    logger.warning(f"[FeishuMsg] PPT文件消息发送失败(不影响卡片): {file_err}")

            # 构建结果卡片（传入文件上传结果）
            card = self._build_result_card(workflow_id, result, ppt_uploaded=ppt_uploaded)

            # 发送卡片消息
            await feishu_api.send_interactive_card(
                receive_id=chat_id,
                card_content=card,
                receive_id_type="chat_id"
            )

            logger.info(f"[FeishuMsg] 工作流结果已发送到飞书: {workflow_id}")
            return True

        except Exception as e:
            logger.error(f"[FeishuMsg] 发送工作流结果失败: {e}")
            # 尝试发送文本消息作为降级方案
            try:
                await feishu_api.send_text_message(
                    receive_id=chat_id,
                    text=f"工作流 {workflow_id[:8]}... 已完成，但结果展示失败",
                    receive_id_type="chat_id"
                )
            except Exception as send_err:
                logger.warning(f"[FeishuMsg] 降级文本消息也失败: {send_err}")
            return False

    async def send_confirmation_card(
        self,
        chat_id: str,
        workflow_id: str,
        confirm_type: str,
        display_data: Dict[str, Any],
    ) -> bool:
        """发送确认卡片到飞书

        Args:
            chat_id: 飞书会话 ID
            workflow_id: 工作流 ID
            confirm_type: 确认类型 (task_plan/doc_outline/ppt_outline/ppt_content)
            display_data: 展示数据
        Returns:
            bool: 是否发送成功
        """
        try:
            # 构建确认卡片
            card = self._build_confirmation_card(workflow_id, confirm_type, display_data)

            # 发送卡片消息
            send_result = await feishu_api.send_interactive_card(
                receive_id=chat_id,
                card_content=card,
                receive_id_type="chat_id"
            )

            message_id = send_result.get("message_id", "") if isinstance(send_result, dict) else ""
            self._pending_confirmations[workflow_id] = {
                "workflow_id": workflow_id,
                "confirm_type": confirm_type,
                "chat_id": chat_id,
                "message_id": message_id,
            }

            logger.info(f"[FeishuMsg] 确认卡片已发送到飞书: {workflow_id}, type={confirm_type}")
            return True

        except Exception as e:
            logger.error(f"[FeishuMsg] 发送确认卡片失败: {e}")
            return False

    def get_pending_confirmation_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """根据消息ID查找待确认上下文"""
        if not message_id:
            return None
        for item in self._pending_confirmations.values():
            if item.get("message_id") == message_id:
                return item
        return None

    def clear_pending_confirmation(self, workflow_id: str):
        """清理待确认上下文"""
        self._pending_confirmations.pop(workflow_id, None)

    async def send_text_notification(
        self,
        chat_id: str,
        message: str,
    ) -> bool:
        """发送文本通知到飞书

        Args:
            chat_id: 飞书会话 ID
            message: 消息内容
        Returns:
            bool: 是否发送成功
        """
        try:
            await feishu_api.send_text_message(
                receive_id=chat_id,
                text=message,
                receive_id_type="chat_id"
            )
            return True
        except Exception as e:
            logger.error(f"[FeishuMsg] 发送文本消息失败: {e}")
            return False

    async def _send_modify_card(
        self,
        chat_id: str,
        workflow_id: str,
        confirm_type: str,
    ) -> bool:
        """发送修改意见输入卡片到飞书

        Args:
            chat_id: 飞书会话 ID
            workflow_id: 工作流 ID
            confirm_type: 确认类型
        Returns:
            bool: 是否发送成功
        """
        try:
            # 构建修改卡片
            card = self._build_modify_input_card(workflow_id, confirm_type)

            # 发送卡片消息
            await feishu_api.send_interactive_card(
                receive_id=chat_id,
                card_content=card,
                receive_id_type="chat_id"
            )

            logger.info(f"[FeishuMsg] 修改卡片已发送到飞书: {workflow_id}, type={confirm_type}")
            return True

        except Exception as e:
            logger.error(f"[FeishuMsg] 发送修改卡片失败: {e}")
            return False

    def _build_result_card(
        self,
        workflow_id: str,
        result: Dict[str, Any],
        ppt_uploaded: bool = False,
    ) -> Dict[str, Any]:
        """构建工作流结果卡片"""
        # 从result中直接获取文档和PPT链接
        doc_url = result.get("doc_url", "")
        ppt_url = result.get("ppt_url", "")
        doc_title = "生成的文档"
        ppt_title = "生成的PPT"
        ppt_mock = ppt_url.startswith("mock://") if ppt_url else False
        
        # 尝试从delivery中获取标题和链接（delivery_node中组装的数据）
        delivery = result.get("delivery", {})
        if delivery:
            doc_title = delivery.get("doc_title", doc_title)
            ppt_title = delivery.get("ppt_title", ppt_title)
            # 如果delivery中有artifacts，从中提取链接
            artifacts = delivery.get("artifacts", [])
            for artifact in artifacts:
                if artifact.get("type") == "doc" and artifact.get("url"):
                    doc_url = artifact.get("url")
                    doc_title = artifact.get("title", doc_title)
                elif artifact.get("type") == "ppt" and artifact.get("url"):
                    ppt_url = artifact.get("url")
                    ppt_title = artifact.get("title", ppt_title)

        elements = []

        # 成功状态图标+标题
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🎉 任务已成功完成**\n工作流 ID: {workflow_id[:8]}"
            },
            "icon": {
                "tag": "standard_icon",
                "token": "task_done_filled",
                "color": "#00B42A"
            }
        })

        elements.append({"tag": "hr"})

        # 文档结果
        if doc_url:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📄 文档结果**\n[{doc_title}]({doc_url})"
                }
            })
            elements.append({"tag": "hr"})

        # PPT结果
        if ppt_url and ppt_mock:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📊 PPT结果**\n{ppt_title}（模拟模式，未实际生成文件）"
                }
            })
            elements.append({"tag": "hr"})
        elif ppt_url:
            ppt_text = f"**📊 PPT结果**\n{ppt_title}"
            if ppt_uploaded:
                ppt_text += "\n✅ PPT文件已作为附件发送，可在消息中查看和下载"
            else:
                ppt_text += "\n⚠️ PPT文件已生成，但上传到飞书失败，请联系管理员"
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": ppt_text
                }
            })
            elements.append({"tag": "hr"})

        if not doc_url and not ppt_url:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "plain_text",
                    "content": "✅ 任务已完成，无生成的文档或PPT"
                },
                "icon": {
                    "tag": "standard_icon",
                    "token": "check_circle_outlined",
                    "color": "#00B42A"
                }
            })
            elements.append({"tag": "hr"})

        # 时间戳
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "standard_icon",
                    "token": "time_outlined",
                    "color": "#86909C"
                },
                {
                    "tag": "plain_text",
                    "content": f" 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            ]
        })

        return {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "green",
                "title": {"content": "✅ 任务完成", "tag": "plain_text"}
            },
            "elements": elements
        }

    def _build_confirmation_card(
        self,
        workflow_id: str,
        confirm_type: str,
        display_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建确认卡片（Card DSL 2.0）"""
        # 根据 confirm_type 构建待审核内容的展示文本
        type_labels = {
            "task_plan": "任务计划",
            "doc_outline": "文档大纲",
            "ppt_outline": "PPT大纲",
            "ppt_content": "PPT内容",
        }
        type_label = type_labels.get(confirm_type, confirm_type)

        # 提取待审核内容
        content = display_data.get("formatted", display_data.get("content", ""))
        if isinstance(content, dict):
            content = content.get("summary", content.get("text", str(content)))
        content_preview = str(content)[:2000] if content else "（暂无内容）"

        review_content = f"**待审核内容：**\n{content_preview}\n\n请查看上方需要审核的{type_label}，确认无误后可进行操作。"

        return {
            "name": "任务确认",
            "dsl": {
                "body": {
                    "elements": [
                        {
                            "direction": "vertical",
                            "elements": [
                                {
                                    "content": review_content,
                                    "tag": "markdown",
                                    "text_size": "normal"
                                },
                                {
                                    "content": "请确认当前任务操作，如需修改请填写具体内容",
                                    "tag": "markdown",
                                    "text_size": "normal"
                                },
                                {
                                    "margin": "0px 0px 12px 0px",
                                    "name": "modify_content",
                                    "placeholder": {
                                        "content": "请输入需要修改的内容...",
                                        "tag": "plain_text"
                                    },
                                    "required": False,
                                    "tag": "input",
                                    "width": "fill"
                                },
                                {
                                    "columns": [
                                        {
                                            "elements": [
                                                {
                                                    "form_action_type": "submit",
                                                    "margin": "4px 0px 4px 0px",
                                                    "name": "confirm_btn",
                                                    "tag": "button",
                                                    "text": {
                                                        "content": "确认",
                                                        "tag": "plain_text"
                                                    },
                                                    "type": "primary_filled",
                                                    "width": "fill"
                                                }
                                            ],
                                            "horizontal_align": "left",
                                            "tag": "column",
                                            "vertical_align": "top",
                                            "vertical_spacing": "8px",
                                            "width": "auto"
                                        },
                                        {
                                            "elements": [
                                                {
                                                    "form_action_type": "submit",
                                                    "margin": "4px 0px 4px 0px",
                                                    "name": "modify_btn",
                                                    "tag": "button",
                                                    "text": {
                                                        "content": "修改",
                                                        "tag": "plain_text"
                                                    },
                                                    "type": "primary",
                                                    "width": "fill"
                                                }
                                            ],
                                            "horizontal_align": "left",
                                            "tag": "column",
                                            "vertical_align": "top",
                                            "vertical_spacing": "8px",
                                            "width": "auto"
                                        },
                                        {
                                            "elements": [
                                                {
                                                    "form_action_type": "submit",
                                                    "margin": "4px 0px 4px 0px",
                                                    "name": "cancel_btn",
                                                    "tag": "button",
                                                    "text": {
                                                        "content": "取消任务",
                                                        "tag": "plain_text"
                                                    },
                                                    "type": "danger_filled",
                                                    "width": "fill"
                                                }
                                            ],
                                            "horizontal_align": "left",
                                            "tag": "column",
                                            "vertical_align": "top",
                                            "vertical_spacing": "8px",
                                            "width": "auto"
                                        }
                                    ],
                                    "flex_mode": "flow",
                                    "horizontal_align": "left",
                                    "horizontal_spacing": "8px",
                                    "tag": "column_set"
                                }
                            ],
                            "horizontal_align": "left",
                            "margin": "0px",
                            "name": "task_confirm_form",
                            "padding": "12px 12px 12px 12px",
                            "tag": "form",
                            "vertical_align": "top",
                            "vertical_spacing": "12px"
                        }
                    ]
                },
                "config": {
                    "update_multi": True
                },
                "header": {
                    "padding": "12px 8px 12px 8px",
                    "subtitle": {
                        "content": "",
                        "tag": "plain_text"
                    },
                    "template": "blue",
                    "title": {
                        "content": "任务确认",
                        "tag": "plain_text"
                    }
                },
                "schema": "2.0"
            },
            "variables": []
        }

    def _build_modify_input_card(
        self,
        workflow_id: str,
        confirm_type: str,
    ) -> Dict[str, Any]:
        """构建修改意见输入卡片"""
        type_config = {
            "task_plan": {"name": "任务计划", "icon": "edit_filled"},
            "doc_outline": {"name": "文档大纲", "icon": "edit_filled"},
            "ppt_outline": {"name": "PPT大纲", "icon": "edit_filled"},
            "ppt_content": {"name": "PPT内容", "icon": "edit_filled"},
        }
        config = type_config.get(confirm_type, {"name": "内容", "icon": "edit_filled"})
        type_name = config["name"]

        return {
            "config": {"wide_screen_mode": True, "enable_forward": False},
            "header": {
                "template": "orange",
                "title": {"content": f"✏️ 修改{type_name}", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**请描述您对{type_name}的修改意见**\n工作流 ID: {workflow_id[:8]}"
                    },
                    "icon": {
                        "tag": "standard_icon",
                        "token": config["icon"],
                        "color": "#FF7D00"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**✅ 请返回上方的确认卡片，在输入框中填写修改意见后点击【修改】按钮提交。**\n\n**示例：**\n• 增加AI伦理相关章节\n• 删除第三部分内容\n• 把技术现状写得更详细\n• 调整章节顺序，把结论放前面"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "standard_icon",
                            "token": "check_circle_filled",
                            "color": "#00B42A"
                        },
                        {
                            "tag": "plain_text",
                            "content": " 已修复：现在输入修改意见不会开启新的工作流"
                        }
                    ]
                }
            ]
        }


    def build_action_result_card(
        self,
        workflow_id: str,
        action_type: str,
        confirm_type: str = "",
        extra_info: str = "",
    ) -> Dict[str, Any]:
        """构建操作结果卡片，用于替换原确认卡片"""
        type_labels = {
            "task_plan": "任务计划",
            "doc_outline": "文档大纲",
            "ppt_outline": "PPT大纲",
            "ppt_content": "PPT内容",
        }
        type_label = type_labels.get(confirm_type, "内容")

        action_config = {
            "confirm": {
                "header_template": "green",
                "header_title": "✅ 已确认",
                "icon": "check_circle_filled",
                "icon_color": "#00B42A",
                "status_text": f"**{type_label}已确认，正在继续执行...**",
            },
            "modify": {
                "header_template": "orange",
                "header_title": "✏️ 已提交修改",
                "icon": "edit_filled",
                "icon_color": "#FF7D00",
                "status_text": f"**{type_label}修改意见已提交，正在重新生成...**"
                    + (f"\n\n修改内容：{extra_info[:200]}" if extra_info else ""),
            },
            "cancel": {
                "header_template": "red",
                "header_title": "❌ 已取消",
                "icon": "close_circle_filled",
                "icon_color": "#F53F3F",
                "status_text": f"**{type_label}任务已取消**",
            },
        }

        cfg = action_config.get(action_type, action_config["confirm"])

        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": cfg["status_text"],
                },
                "icon": {
                    "tag": "standard_icon",
                    "token": cfg["icon"],
                    "color": cfg["icon_color"],
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "standard_icon",
                        "token": "time_outlined",
                        "color": "#86909C",
                    },
                    {
                        "tag": "plain_text",
                        "content": f" 操作时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    },
                ],
            },
        ]

        return {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": cfg["header_template"],
                "title": {"content": cfg["header_title"], "tag": "plain_text"},
            },
            "elements": elements,
        }


# 全局服务实例
feishu_message_service = FeishuMessageService()
