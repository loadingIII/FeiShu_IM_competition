# 飞书长连接与后端服务集成说明

本文档说明如何将飞书机器人长连接与后端工作流服务关联起来，实现完整的"接收事件 → 处理业务 → 响应用户"流程。

## 架构概览

```
┌─────────────────┐     WebSocket      ┌──────────────────┐
│   飞书开放平台   │ ◄────────────────► │   后端服务        │
└─────────────────┘                    │  (FastAPI)       │
                                       └────────┬─────────┘
                                                │
                    ┌───────────────────────────┼───────────┐
                    │                           │           │
                    ▼                           ▼           ▼
           ┌─────────────┐           ┌──────────────┐ ┌──────────┐
           │  长连接管理器 │           │   工作流引擎   │ │ 消息服务  │
           │ (FeishuWS)  │           │(WorkflowMgr) │ │(Feishu)  │
           └─────────────┘           └──────────────┘ └──────────┘
```

## 数据流

### 1. 用户发送消息 → 工作流创建

```
用户发送消息 → 长连接接收 → 创建工作流 → 返回确认
```

**代码位置**: [app/main.py](file:///e:\AI-code\feishu-competition\app\main.py#L23-L44)

### 2. 工作流执行 → 需要确认 → 发送卡片

```
工作流执行 → ConfirmNode → 发送确认卡片到飞书 → 等待用户交互
```

**代码位置**:
- [core_workflow/nodes/ConfirmNode.py](file:///e:\AI-code\feishu-competition\core_workflow\nodes\ConfirmNode.py#L221-L232)
- [app/service/feishu_message_service.py](file:///e:\AI-code\feishu-competition\app\service\feishu_message_service.py#L50-L77)

### 3. 用户点击卡片 → 提交确认 → 工作流继续

```
用户点击卡片按钮 → 长连接接收卡片事件 → 提交确认 → 工作流继续执行
```

**代码位置**:
- [app/service/feishu_ws_manager.py](file:///e:\AI-code\feishu-competition\app\service\feishu_ws_manager.py#L83-L142)
- [app/main.py](file:///e:\AI-code\feishu-competition\app\main.py#L47-L84)

### 4. 工作流完成 → 发送结果

```
工作流完成 → 发送结果卡片到飞书
```

**代码位置**:
- [app/service/workflow.py](file:///e:\AI-code\feishu-competition\app\service\workflow.py#L143-L175)
- [app/service/feishu_message_service.py](file:///e:\AI-code\feishu-competition\app\service\feishu_message_service.py#L21-L48)

## 核心组件

### 1. FeishuWSManager - 长连接管理器

负责管理飞书 WebSocket 长连接，处理消息和卡片事件。

**功能**:
- 接收用户消息 (`im.message.receive_v1`)
- 接收卡片交互 (`card.action.trigger`)
- 后台线程运行，不阻塞主应用

**文件**: [app/service/feishu_ws_manager.py](file:///e:\AI-code\feishu-competition\app\service\feishu_ws_manager.py)

### 2. FeishuMessageService - 消息服务

负责发送消息和卡片到飞书。

**功能**:
- 发送工作流结果卡片
- 发送确认卡片
- 发送文本通知

**文件**: [app/service/feishu_message_service.py](file:///e:\AI-code\feishu-competition\app\service\feishu_message_service.py)

### 3. WorkflowManager - 工作流管理器

负责管理工作流生命周期，集成飞书消息发送。

**文件**: [app/service/workflow.py](file:///e:\AI-code\feishu-competition\app\service\workflow.py)

### 4. ConfirmNode - 确认节点

工作流中的确认节点，支持飞书卡片确认。

**文件**: [core_workflow/nodes/ConfirmNode.py](file:///e:\AI-code\feishu-competition\core_workflow\nodes\ConfirmNode.py)

## 使用步骤

### 1. 配置环境变量

```bash
export FEISHU_APP_ID=cli_xxxxxx
export FEISHU_APP_SECRET=xxxxxxxx
```

### 2. 启动 FastAPI 应用

```bash
python -m uvicorn app.main:app --reload
```

长连接会自动启动。

### 3. 飞书开发者后台配置

1. 登录 [飞书开发者后台](https://open.feishu.cn/app)
2. 选择企业自建应用
3. 进入 **事件与回调 > 事件配置**
4. 选择 **使用长连接接收事件**
5. 添加订阅事件:
   - `im.message.receive_v1` - 接收消息
   - `card.action.trigger` - 卡片交互

### 4. 申请权限

在 **权限管理** 中开通:
- `im:message.p2p_msg:readonly` - 读取单聊消息
- `im:message.group_at_msg:readonly` - 读取群聊@消息
- `im:message:send_as_bot` - 以机器人身份发送消息

### 5. 发布应用

在 **版本管理与发布** 中创建版本并提交审核。

## 交互流程示例

### 场景：用户让机器人生成文档

```
用户: 帮我生成一份产品需求文档

机器人: [发送任务计划确认卡片]
        📋 任务计划
        目标: 生成产品需求文档
        ...
        [确认执行] [需要修改] [取消任务]

用户: [点击"确认执行"]

机器人: ✅ 已确认，正在继续执行...

[工作流执行中...]

机器人: [发送文档大纲确认卡片]
        📄 文档大纲
        标题: 产品需求文档
        ...
        [确认执行] [需要修改] [取消任务]

用户: [点击"需要修改"]

机器人: [发送修改输入卡片]
        ✏️ 修改文档大纲
        请描述您希望如何调整:
        [输入框]
        [提交修改意见]

用户: [输入"增加技术实现章节"] [提交]

机器人: ✏️ 已提交修改意见: 增加技术实现章节...

[工作流重新生成...]

[工作流完成]

机器人: [发送结果卡片]
        🎉 任务完成
        ✅ 工作流 xxx 已完成
        📄 文档: [查看文档](链接)
```

## 注意事项

### 1. 超时处理

长连接接收的事件需在 **3秒内响应**。复杂逻辑已改为异步处理:

```python
# 立即返回响应
asyncio.run_coroutine_threadsafe(
    self._message_callback(chat_id, sender_open_id, text),
    self._loop
)
```

### 2. 消息队列

确认节点使用 `ConfirmationService` 进行异步等待，避免阻塞:

```python
result = await confirmation_service.wait_for_confirmation(
    state["workflow_id"], timeout=300.0
)
```

### 3. 错误处理

所有飞书消息发送都有降级方案:

```python
try:
    await feishu_api.send_interactive_card(...)
except Exception as e:
    # 降级为文本消息
    await feishu_api.send_text_message(...)
```

## 扩展开发

### 添加新的事件处理器

在 `FeishuWSManager._build_event_handler()` 中注册:

```python
def _build_event_handler(self) -> lark.EventDispatcherHandler:
    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(self._on_p2_im_message_receive_v1)
        .register_p2_card_action_trigger(self._on_p2_card_action_trigger)
        .register_p2_xxx_your_event(self._on_your_event)  # 添加新事件
        .build()
    )
```

### 自定义卡片模板

在 `FeishuMessageService` 中添加新方法:

```python
def _build_custom_card(self, data: dict) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {...},
        "elements": [...]
    }
```

## 参考文档

- [飞书长连接文档](file:///e:\AI-code\feishu-competition\core_workflow\feishu_md\长连接.md)
- [飞书长连接与后端服务连接](file:///e:\AI-code\feishu-competition\core_workflow\feishu_md\长连接后与后端服务连接.md)
