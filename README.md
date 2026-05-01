# FeiShu IM Competition（Agent-Pilot）

一个基于 **LangGraph + FastAPI + 飞书开放平台** 的多阶段 Agent 工作流项目，支持从聊天消息中自动完成：

- 文档生成（飞书 Docx）
- PPT 生成（本地 `.pptx`）
- 计划确认 / 修改反馈 / 取消
- WebSocket 实时状态推送
- 飞书机器人（Webhook 或长连接）交互

---

## 给 Claude Code 的快速阅读入口（建议顺序）

1. `app/main.py`：服务入口、路由挂载、飞书长连接启动
2. `app/service/workflow.py`：工作流生命周期（创建、运行、确认、取消）
3. `core_workflow/graph/graph.py`：LangGraph 拓扑与条件路由
4. `core_workflow/state/state.py`：全局状态 `IMState` 字段定义
5. `core_workflow/nodes/*.py`：各场景节点实现（Router/Plan/Confirm/Doc/PPT/Delivery）
6. `app/router/workflows.py`：对外 API 合同
7. `app/service/websocket.py`：前端订阅消息协议

---

## 项目结构（核心）

```text
app/
  main.py                    # FastAPI 入口
  router/
    workflows.py             # 工作流 REST API
    feishu_bot.py            # 飞书 webhook 回调
  service/
    workflow.py              # WorkflowManager（异步执行 LangGraph）
    confirmation.py          # 确认等待/唤醒
    chat.py                  # 聊天输入等待/唤醒
    websocket.py             # WS 连接与广播
    feishu_ws_manager.py     # 飞书长连接管理
    feishu_message_service.py# 飞书卡片/通知发送
  crud/workflow.py           # 内存态工作流存储
  model/__init__.py          # WorkflowInstance / 状态枚举

core_workflow/
  graph/graph.py             # 工作流图定义
  state/state.py             # IMState
  nodes/
    RouterNode.py            # 场景A：意图识别
    PlanNode.py              # 场景B：任务规划
    ConfirmNode.py           # 确认节点（API/CLI 两模式）
    TextGenerateNode.py      # 场景C：文档生成
    PPTGenerateNode.py       # 场景D：PPT生成
    MultiTerminalNode.py     # 场景E：多端同步（占位）
    DeliveryNode.py          # 场景F：交付汇总
```

---

## 运行流程（A-F）

1. **A Router**：识别用户意图，必要时拉取飞书群历史做上下文摘要  
2. **B Plan**：生成任务计划（文档 / PPT / 二者）  
3. **Confirm**：用户确认计划或反馈修改  
4. **C Doc**：生成文档大纲 -> 确认 -> 生成内容 -> 写入飞书文档  
5. **D PPT**：生成大纲 -> 确认 -> 生成内容 -> 调用 Node.js 生成 `.pptx`  
6. **E MultiTerminal**：多端同步（当前实现较轻）  
7. **F Delivery**：汇总产物，向前端/飞书回传结果  

---

## 本地启动

> 建议在仓库根目录执行（很多路径逻辑假设 cwd 为项目根）。

### 1) Python 依赖

```powershell
pip install -r requirements.txt
```

### 2) Node 依赖（PPT 生成需要）

```powershell
Set-Location core_workflow
npm install
Set-Location ..
```

### 3) 启动服务

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：`GET /health`

---

## 环境变量

最小建议配置：

```env
# LLM
QWEN_KEY=xxx
QWEN_MODEL=xxx
QWEN_URL=https://xxx/v1
ROUTER_MODEL=xxx

# 飞书（消息收发/文档写入/长连接）
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx

# 可选：Webhook 验签
FEISHU_ENCRYPT_KEY=
FEISHU_VERIFICATION_TOKEN=
```

---

## API 速查

### 工作流 REST（`app/router/workflows.py`）

- `POST /workflows`：创建工作流
- `GET /workflows/{workflow_id}`：查询工作流状态
- `POST /workflows/{workflow_id}/confirm`：确认/修改/取消
- `POST /workflows/{workflow_id}/chat`：给等待中的工作流发送消息
- `POST /workflows/{workflow_id}/cancel`：强制取消
- `GET /workflows`：最近工作流列表

### 飞书入口（`app/router/feishu_bot.py`）

- `POST /feishu-bot/webhook`：飞书事件回调
- `POST /feishu-bot/send-message`：主动向飞书会话发消息

### 前端 WS（`/ws`）

客户端上行：

- `{"type":"ping"}`
- `{"type":"subscribe","workflowId":"..."}`
- `{"type":"unsubscribe","workflowId":"..."}`

服务端下行（典型）：

- `workflow_created`
- `scene_started` / `scene_completed` / `scene_failed`
- `confirm_required` / `confirm_result`
- `chat_message`
- `workflow_completed` / `workflow_failed` / `workflow_cancelled`

---

## 对 Claude Code 特别有用的事实

1. **状态存储是内存态**：`app/crud/workflow.py` 使用进程内字典，无数据库持久化。  
2. **确认机制是异步阻塞点**：`ConfirmationService` 用 `Event` 挂起流程，直到 API/飞书卡片回传。  
3. **PPT 文件由 Node.js 生成**：`PPTGenerateNode.py` 会生成临时 JS，再调用 `node` 产出 `.pptx`。  
4. **文档直接写飞书 Docx**：`TextGenerateNode.py` 调用 `utils/feishuUtils.py` 创建文档与块。  
5. **日志集中在 `logs/`**：默认 logger 同时输出控制台 + 文件。  

---

## 变更定位指南（常见需求 -> 文件）

- 调整流程分支：`core_workflow/graph/graph.py`
- 改意图识别逻辑：`core_workflow/nodes/RouterNode.py` + `nodes/agent/prompt/router_prompt.py`
- 改确认交互：`core_workflow/nodes/ConfirmNode.py` + `app/service/confirmation.py`
- 改文档生成：`core_workflow/nodes/TextGenerateNode.py`
- 改 PPT 版式/风格：`core_workflow/nodes/PPTGenerateNode.py`
- 改飞书卡片样式：`app/service/feishu_message_service.py`
- 改前端 WS 事件协议：`app/service/websocket.py`

---

## 已知注意点（阅读时请优先关注）

1. `app/main.py` 中飞书来源通常使用 `source="feishu_bot"`，而 `RouterNode` 仅在 `source=="feishu_im"` 时拉群聊历史。  
2. `MultiTerminalNode` 目前逻辑较轻，更多是流程汇合点。  
3. `core_workflow/main.py` 更像历史调试入口，实际服务入口是 `app/main.py`。  

---

## 补充文档

如果要深入飞书接入与流程设计，继续看：

- `core_workflow/feishu_md/design/Agent-Pilot-Workflow-Design.md`
- `core_workflow/feishu_md/FEISHU_INTEGRATION_README.md`
- `core_workflow/feishu_md/FEISHU_WS_README.md`

