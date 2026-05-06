# Agent-Pilot — 飞书 IM 竞赛 AI 工作流

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-FF6F00?logo=langchain)](https://langchain-ai.github.io/langgraph/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)

基于 **LangGraph + FastAPI + 飞书开放平台** 的多阶段 AI Agent 工作流。输入自然语言，自动规划、生成飞书文档与 PPT，并交付到飞书会话。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 🤖 意图识别 | 自动区分闲聊、知识问答与任务意图（文档/PPT/会议纪要） |
| 📋 任务规划 | 根据意图自动拆解为文档生成、PPT 制作等子任务 |
| 📄 文档生成 | 智能生成大纲 → 经人工确认后 → 生成完整内容 → 写入飞书 Docx |
| 📊 PPT 生成 | 生成大纲 → 确认 → 内容 → 确认 → 通过 PptxGenJS 产出 `.pptx` 文件 |
| ✅ 人工确认 | 每个关键节点支持 **确认 / 修改反馈 / 取消** |
| 💬 闲聊模式 | 非任务消息由 chat_llm 直接回复，不进入 LangGraph 工作流 |
| 🔔 飞书集成 | 双通道接入（Webhook + WebSocket 长连接）+ 交互式卡片 |
| ⚡ 实时推送 | WebSocket 推送工作流各阶段事件 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 工作流引擎 | LangGraph + LangChain |
| LLM 接入 | OpenAI 兼容接口（通义千问 DashScope） |
| 飞书 SDK | lark-oapi（消息/卡片/文档/云空间） |
| PPT 生成 | Node.js + pptxgenjs（Python 动态生成 JS 代码执行） |
| 通信 | REST API + WebSocket + 飞书长连接 |

## 项目结构

```text
app/
  main.py                     # FastAPI 入口、/ws、生命周期管理
  router/
    workflows.py              # 工作流 REST API
    feishu_bot.py             # 飞书 webhook / 卡片回调
  service/
    workflow.py               # WorkflowManager：统一消息入口 + 工作流生命周期
    websocket.py              # WebSocket 广播协议
    confirmation.py           # 人工确认的 async 阻塞/唤醒
    feishu_ws_manager.py      # 飞书长连接管理（WebSocket 客户端）
    feishu_message_service.py # 飞书卡片构建与发送
    feishu_ws_server.py       # 飞书长连接服务端
  crud/workflow.py            # 内存态工作流 CRUD
  model/__init__.py           # WorkflowStatus / WorkflowInstance
  schema/__init__.py          # API 请求响应模型

core_workflow/
  graph/graph.py              # LangGraph StateGraph 拓扑与路由
  state/state.py              # IMState 全局状态定义
  nodes/
    RouterNode.py             # 场景A：意图识别
    PlanNode.py               # 场景B：任务规划
    TextGenerateNode.py       # 场景C：文档大纲 + 内容生成 + Feishu Docx 写入
    PPTGenerateNode.py        # 场景D：PPT 大纲 + 内容 + PptxGenJS 文件生成
    ConfirmNode.py            # 人工确认节点（确认/修改/取消）
    MultiTerminalNode.py      # 场景E：多端同步
    DeliveryNode.py           # 场景F：汇总交付
  agent/
    router_agent.py           # 意图识别 Agent
    chat_agent.py             # 闲聊 Agent
    ppt_generate_agent.py     # PPT 生成 Agent
    text_generate_agent.py    # 文档生成 Agent
    llm/                      # LLM 配置与链定义
    prompt/                   # 各 Agent 系统提示词
```

## 工作流架构

```
用户消息 (飞书 / API / WebSocket)
  │
  ├─ 轻量意图判断 → 闲聊/知识问答 → chat_llm 直接回复
  │
  └─ 任务意图 → WorkflowManager.create_workflow()
                  │
     ┌─────────────┴──────────────┐
     │     LangGraph StateGraph    │
     │                             │
     │  A: RouterNode              │  意图识别 + 上下文增强
     │       ↓                     │
     │  B: PlanNode                │  任务规划（doc / ppt / both）
     │       ↓                     │
     │  C: ConfirmNode ←→ 用户确认  │  人工确认（卡片交互）
     │       ↓                     │
     │  D: TextGenerateNode        │  文档大纲 → 确认 → 内容 → Feishu Docx
     │       ↓                     │
     │  E: PPTGenerateNode         │  PPT大纲 → 确认 → 内容 → 确认 → .pptx
     │       ↓                     │
     │  F: DeliveryNode            │  汇总结果，推送飞书
     └─────────────────────────────┘
```

## 快速开始

> 所有命令在仓库**根目录**执行（项目内部路径依赖 CWD）。

### 安装

```powershell
# 1. Python 依赖
pip install -r requirements.txt

# 2. Node.js 依赖（PPT 生成必需）
cd core_workflow
npm install
cd ..
```

### 配置

在根目录创建 `.env`：

```env
# LLM（OpenAI 兼容接口，当前使用阿里云 DashScope）
QWEN_KEY=sk-xxx
QWEN_MODEL=qwen3.5-plus
QWEN_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ROUTER_MODEL=deepseek-v4-flash

# 飞书应用凭证
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# 可选：Webhook 验签
FEISHU_ENCRYPT_KEY=
FEISHU_VERIFICATION_TOKEN=
```

### 启动

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **健康检查**: `GET /health`
- **Swagger 文档**: `http://127.0.0.1:8000/docs`
- **CLI 调试**: `python core_workflow/main.py`

## API 概览

### 工作流（`/workflows`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/workflows` | 创建并启动工作流 |
| GET | `/workflows/{id}` | 查询工作流状态 |
| POST | `/workflows/{id}/confirm` | 确认/修改/取消 |
| POST | `/workflows/{id}/cancel` | 强制取消 |
| GET | `/workflows` | 最近工作流列表 |

```bash
curl -X POST "http://127.0.0.1:8000/workflows" \
  -H "Content-Type: application/json" \
  -d "{\"user_input\":\"请生成一份AI行业研究报告并配套PPT\"}"
```

### 飞书机器人（`/feishu-bot`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/feishu-bot/webhook` | 飞书事件订阅回调 |
| POST | `/feishu-bot/send-message` | 主动发送飞书消息 |

### WebSocket（`/ws`）

**上行：**

```json
{"type":"ping"}
{"type":"subscribe","workflowId":"..."}
{"type":"unsubscribe","workflowId":"..."}
```

**下行事件：**

| 事件 | 说明 |
|------|------|
| `workflow_created` | 工作流已创建 |
| `scene_started` | 场景开始（A~F） |
| `scene_completed` | 场景完成 |
| `scene_failed` | 场景失败 |
| `confirm_required` | 等待用户确认 |
| `confirm_result` | 确认结果 |
| `chat_message` | 闲聊消息 |
| `workflow_completed` | 工作流完成 |
| `workflow_failed` | 工作流失败 |
| `workflow_cancelled` | 工作流取消 |

## 场景对照

| 场景 | 节点 | 功能 |
|------|------|------|
| A | `RouterNode` | 意图识别 + 群聊上下文摘要 |
| B | `PlanNode` | 任务规划（分支选择） |
| C | `TextGenerateNode` | 文档大纲 → 确认 → 内容 → Feishu Docx |
| D | `PPTGenerateNode` | PPT大纲 → 确认 → 内容 → 确认 → .pptx |
| E | `MultiTerminalNode` | 多端同步（预留） |
| F | `DeliveryNode` | 汇总结果，飞书通知 |

## LLM 配置

双模型架构（均为 OpenAI 兼容接口）：

| 用途 | 模型 | 温度 |
|------|------|------|
| 意图识别 + 规划 | `deepseek-v4-flash` | 0.2~0.5 |
| 文档/PPT/闲聊/摘要 | `qwen3.5-plus` | 0.2~0.7 |

## 注意事项

- **内存存储**：工作流状态存于内存，服务重启后丢失
- **飞书凭证**：文档生成依赖飞书 Docx API，未配置不可用
- **服务入口**：`app/main.py` 为实际服务入口；`core_workflow/main.py` 仅用于 CLI 调试
- **文件清理**：PPT 生成产生的临时 `.js` 和 `.pptx` 文件不会自动清理

## 文档

- [工作流设计文档](core_workflow/feishu_md/design/Agent-Pilot-Workflow-Design.md)
- [飞书集成说明](core_workflow/feishu_md/FEISHU_INTEGRATION_README.md)
- [飞书长连接说明](core_workflow/feishu_md/FEISHU_WS_README.md)