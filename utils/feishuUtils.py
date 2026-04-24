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
                messages = []
                for item in data["data"]["items"]:
                    if not item.get("deleted"):
                        try:
                            content = json.loads(item["body"]["content"])
                            text_content = content.get("text", "")
                            if text_content:
                                sender_name = item["sender"].get("name", "未知用户")
                                messages.append(f"{sender_name}: {text_content}")
                        except:
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

feishu_api = FeishuAPI()
