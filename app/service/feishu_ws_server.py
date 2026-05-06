#!/usr/bin/env python3
"""
飞书长连接服务端
使用 WebSocket 长连接模式接收飞书事件，替代传统的 Webhook 方式

使用方法:
    python feishu_ws_server.py

环境变量:
    FEISHU_APP_ID: 飞书应用 ID
    FEISHU_APP_SECRET: 飞书应用密钥

配置说明:
    1. 在飞书开发者后台 https://open.feishu.cn/app 选择企业自建应用
    2. 进入 事件与回调 > 事件配置 页面
    3. 编辑订阅方式，选择 "使用长连接接收事件"，并保存
    4. 确保本地客户端启动正常，有长连接在线的情况下，才能保存成功
"""
import os
import sys
import asyncio
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.service.feishu_ws_client import FeishuWSClient
from app.service import workflow_manager
from utils.logger_handler import logger


async def handle_user_message(chat_id: str, sender_open_id: str, message: str):
    """处理用户发送的消息"""
    try:
        await workflow_manager.handle_message(
            user_input=message,
            user_id=sender_open_id,
            source="feishu_bot",
            chat_id=chat_id,
            sender_open_id=sender_open_id,
        )
    except Exception as e:
        logger.error(f"[FeishuWS] 处理用户消息失败: {e}")


def main():
    """主函数"""
    # 检查环境变量
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("错误: 请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量")
        print("示例:")
        print("  export FEISHU_APP_ID=cli_xxxxxx")
        print("  export FEISHU_APP_SECRET=xxxxxx")
        sys.exit(1)

    print("=" * 60)
    print("飞书长连接服务端")
    print("=" * 60)
    print(f"应用 ID: {app_id[:10]}...")
    print("启动中...")
    print("-" * 60)

    # 创建客户端
    client = FeishuWSClient()
    client.set_message_callback(handle_user_message)

    try:
        # 启动客户端（阻塞）
        client.start()
    except KeyboardInterrupt:
        print("\n正在停止服务端...")
    except Exception as e:
        logger.error(f"服务端异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
