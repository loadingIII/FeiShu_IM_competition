import os
import json
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

class FeishuAPI:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.tenant_access_token = None
        self.token_expire_time = None

    async def get_tenant_access_token(self):
        """获取tenant_access_token，自动缓存"""
        if self.tenant_access_token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            })
            data = response.json()
            if data.get("code") == 0:
                self.tenant_access_token = data["tenant_access_token"]
                self.token_expire_time = datetime.now() + timedelta(seconds=data["expire"] - 60)
                return self.tenant_access_token
            else:
                raise Exception(f"获取飞书access_token失败: {data.get('msg')}")

    async def get_chat_members(self, chat_id: str):
        """获取群成员列表，返回 open_id 到用户名称的映射"""
        token = await self.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/members"
        params = {"member_id_type": "open_id", "page_size": 100}
        headers = {"Authorization": f"Bearer {token}"}
        
        member_map = {}
        page_token = None
        
        async with httpx.AsyncClient() as client:
            while True:
                if page_token:
                    params["page_token"] = page_token
                
                response = await client.get(url, params=params, headers=headers)
                data = response.json()
                
                if data.get("code") == 0:
                    items = data["data"].get("items", [])
                    for item in items:
                        member_id = item.get("member_id", "")
                        name = item.get("name", "")
                        if member_id and name:
                            member_map[member_id] = name
                    
                    if not data["data"].get("has_more", False):
                        break
                    page_token = data["data"].get("page_token")
                else:
                    break
        
        return member_map

    async def get_group_history_messages(self, chat_id: str, page_size: int = 50):
        """拉取群聊历史消息"""
        token = await self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": page_size,
            "sort_type": "ByCreateTimeDesc"
        }
        headers = {
            "Authorization": f"Bearer {token}"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            data = response.json()
            if data.get("code") == 0:
                # 先获取群成员名称映射
                member_map = await self.get_chat_members(chat_id)
                
                messages = []
                for item in data["data"]["items"]:
                    if not item.get("deleted"):
                        try:
                            content = json.loads(item["body"]["content"])
                            text_content = content.get("text", "")
                            if text_content:
                                sender = item.get("sender", {})
                                sender_type = sender.get("sender_type", "")
                                sender_id = sender.get("id", "")
                                
                                # 根据发送者类型获取名称
                                if sender_type == "user":
                                    # 从群成员映射中获取用户名称
                                    sender_name = member_map.get(sender_id, "")
                                    if not sender_name:
                                        sender_name = "未知用户"
                                elif sender_type == "app":
                                    sender_name = "机器人"
                                else:
                                    sender_name = "未知用户"
                                
                                messages.append(f"{sender_name}: {text_content}")
                        except Exception:
                            continue
                return "\n".join(reversed(messages))
            else:
                error_code = data.get("code")
                error_msg = data.get("msg", "")
                if error_code == 230006 or "Bot ability is not activated" in error_msg:
                    raise Exception(
                        f"拉取群聊历史失败: {error_msg}\n"
                        "\n【解决方案】请在飞书开发者后台启用机器人能力："
                        "\n1. 访问 https://open.feishu.cn/app"
                        "\n2. 进入应用详情页 → 应用能力 → 启用机器人能力"
                        "\n3. 创建新版本并发布应用"
                        "\n详细文档：https://open.feishu.cn/document/uAjLw4CM/ugTN1YjL4UTN24CO1UjN/trouble-shooting/how-to-enable-bot-ability"
                    )
                elif error_code == 230002 or "bot can not be outside the group" in error_msg.lower():
                    raise Exception(
                        f"拉取群聊历史失败: {error_msg}\n"
                        "\n【解决方案】请将机器人添加到目标群组中"
                    )
                elif error_code == 230013 or "Bot has NO availability" in error_msg:
                    raise Exception(
                        f"拉取群聊历史失败: {error_msg}\n"
                        "\n【解决方案】请在应用发布页面配置可用范围，将目标用户/群组添加到可用范围内"
                    )
                else:
                    raise Exception(f"拉取群聊历史失败: {error_msg} (错误码: {error_code})")

    async def create_document(self, title: str, folder_token: str = None) -> dict:
        """创建飞书文档
        
        Args:
            title: 文档标题
            folder_token: 可选的文件夹token
            
        Returns:
            包含 document_id 的文档信息
            
        Raises:
            Exception: 创建失败时抛出异常
        """
        token = await self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/docx/v1/documents"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {"title": title}
        if folder_token:
            payload["folder_token"] = folder_token
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            data = response.json()
            if data.get("code") == 0:
                return data["data"]["document"]
            else:
                raise Exception(f"创建飞书文档失败: {data.get('msg')} (错误码: {data.get('code')})")

    async def create_document_blocks(self, document_id: str, block_id: str, children: list) -> dict:
        """在文档中创建内容块
        
        Args:
            document_id: 文档ID
            block_id: 父块ID（使用document_id表示根节点）
            children: 子块列表，每次最多50个
            
        Returns:
            创建结果
            
        Raises:
            Exception: 创建失败时抛出异常
        """
        token = await self.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {"children": children}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            data = response.json()
            if data.get("code") == 0:
                return data["data"]
            else:
                raise Exception(f"创建文档块失败: {data.get('msg')} (错误码: {data.get('code')})")


feishu_api = FeishuAPI()
