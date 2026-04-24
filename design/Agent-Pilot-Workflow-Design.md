# Agent-Pilot 工作流设计文档

> 本文档专注于"工作流怎么跑"，理清场景之间的串联、数据流转、决策分支和用户交互点。

---

## 一、全局视角：工作流从哪里开始？

### 1.1 触发入口

```
入口 1：飞书 IM Bot（主要入口）
─────────────────────────────
触发方式：
  · 群聊中 @Agent-Pilot + 指令文本
  · 单聊中直接发送指令文本
  · 飞书卡片按钮点击

入口 2：飞书 H5 网页应用（可视化交互入口）
─────────────────────────────
触发方式：
  · 对话输入框发送文本
  · 快捷按钮（"生成会议纪要"、"生成周报"等）
  · 从飞书 IM 卡片跳转进入
```

**关键设计**：两个入口最终都汇聚到同一个后端 Agent 引擎，区别仅在于：
- 触发来源标识不同（`source` 字段：`feishu_im` / `h5`）
- 交互方式不同（飞书 IM 用卡片消息，H5 用 Vue 组件）
- 状态推送目标不同（通过 WebSocket 推送到所有已连接的 H5 客户端 + 飞书 IM 消息推送）

### 1.2 统一启动流程

```
用户输入（任意入口）
    │
    ▼
┌─────────────────────────────────────┐
│  Step 0: 请求预处理                   │
│                                     │
│  1. 记录来源（feishu_im / h5）       │
│  2. 生成 workflow_id（UUID）         │
│  3. 创建 Workflow 记录（状态=pending）│
│  4. 通知所有已连接客户端："新工作流"   │
│  5. 如果是飞书 IM：                   │
│     - 拉取群聊最近 N 条消息作为上下文  │
│     - 提取 @消息中的文本内容           │
│  6. 进入场景 A                       │
└─────────────────────────────────────┘
```

---

## 二、核心架构：C/D 并列生成

### 2.1 设计理念

**文档和 PPT 是同一份信息的两种并列呈现形式，不存在先后依赖。**

```
用户需求："整理会议纪要并生成汇报PPT"

本质上是：
  同一份信息 ──┬── 以「文档」形式呈现（详细、可编辑）
               └── 以「PPT」形式呈现（精炼、可演示）

两者都直接从「意图 + 上下文 + 任务计划」生成，不需要互相依赖。
```

### 2.2 并列 vs 串行对比

```
❌ 串行（旧设计）：
A → B → C → D → E → F
                ↑
           PPT 必须等文档写完才能开始
           总耗时 = A + B + C + D + E + F

✅ 并列（新设计）：
A → B ─┬→ C ─┬→ E → F
        └→ D ─┘
           ↑
      C 和 D 同时执行，取最长时间
      总耗时 = A + B + max(C, D) + E + F
```

### 2.3 主工作流拓扑

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
              ┌────►│  场景 A   │
              │     │  意图捕捉  │
              │     └────┬─────┘
              │          │
              │          ▼
              │     ┌──────────┐
              │     │  场景 B   │
              │     │  任务规划  │
              │     └────┬─────┘
              │          │
              │     ┌────┴────┐
              │     │ 用户确认  │
              │     └────┬────┘
              │          │
              │     ┌────┴────────────────────┐
              │     │                         │
              │  需要文档?                 需要PPT?
              │     │                         │
              │     ▼                         ▼
              │ ┌──────────┐            ┌──────────┐
              │ │  场景 C   │            │  场景 D   │
              │ │  文档生成  │            │  PPT 生成  │
              │ │  (含确认)  │            │  (自动)   │
              │ └────┬─────┘            └────┬─────┘
              │      │                       │
              │      │         ┌─────────┐   │
              │      └────────►│ 场景 E  │◄──┘
              │                │ 多端同步 │
              │                │ (汇合点) │
              │                └────┬────┘
              │                     │
              │                ┌────┴────┐
              │                │ 场景 F  │
              │                │ 总结交付 │
              │                └────┬────┘
              │                     │
              └─────────────────────► END
```

**关键语义**：
- 场景 E 是 C 和 D 的**汇合点**，LangGraph 的并行边机制保证 E 只在 C 和 D 都完成后才执行
- 如果只触发了 C 或 D 中的一个，E 在该分支完成后直接执行

---

## 三、全局数据流

### 3.1 State 对象设计

```
                    State 对象（贯穿全流程）
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  ═══ 不变字段（创建时写入）═══                                  │
│  workflow_id ─────────────── 全程不变                         │
│  user_id ─────────────────── 全程不变                         │
│  user_input ──────────────── 全程不变                         │
│  source ──────────────────── 全程不变                         │
│                                                              │
│  ═══ 场景 A 输出 ═══                                           │
│  intent ──────────────── [场景A写入] ──► [场景B读取]          │
│  chat_context ─────────── [场景A写入] ──► [场景B/C/D读取]     │
│                                                              │
│  ═══ 场景 B 输出 ═══                                           │
│  task_plan ────────────── [场景B写入] ──► [场景C/D/E/F读取]   │
│                                                              │
│  ═══ 场景 C 输出（独立于 D）═══                                │
│  doc_outline ───────────── [场景C写入] ──► [场景C内部/用户确认]│
│  doc_content ───────────── [场景C写入] ──► [场景E/F读取]      │
│  doc_url ───────────────── [场景C写入] ──► [场景E/F读取]      │
│                                                              │
│  ═══ 场景 D 输出（独立于 C）═══                                │
│  ppt_structure ─────────── [场景D写入] ──► [场景D内部]        │
│  ppt_content ───────────── [场景D写入] ──► [场景E/F读取]      │
│  ppt_url ───────────────── [场景D写入] ──► [场景E/F读取]      │
│                                                              │
│  ═══ 场景 F 输出 ═══                                           │
│  delivery ──────────────── [场景F写入] ──► 最终输出           │
│                                                              │
│  ═══ 控制流 ═══                                               │
│  messages ──────────────── [各场景追加] ──► 全程日志           │
│  current_scene ─────────── [各场景更新] ──► 客户端展示         │
│  need_confirm ──────────── [控制流设置] ──► 决定是否暂停       │
│  confirmed ─────────────── [用户操作] ──► 决定是否继续         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**关键变化**：`doc_content` 不再流向场景 D。C 和 D 都直接从 `intent + chat_context + task_plan` 获取输入，互不依赖。

### 3.2 完整步骤（带时间线）

```
时间线    场景    动作                           用户可见
──────────────────────────────────────────────────────────────
T+0s      启动    用户发送指令                     "已收到，正在分析..."
T+1s      A       预处理文本                       [场景A 运行中]
T+3s      A       LLM 意图识别                     [场景A 完成 ✓]
                  输出: intent + chat_context
                  广播: intent 结果到客户端
                  │
T+4s      B       LLM 任务规划                     [场景B 运行中]
T+8s      B       输出: task_plan（含并列分支）
                  广播: task_plan 到客户端
                  │
T+8s      ⏸️      暂停：等待用户确认                 ┌──────────────────┐
                  need_confirm = true              │ 任务计划确认       │
                  │                                │ 并列执行:          │
                  │                                │ ☑ 生成文档 (C)    │
                  │                                │ ☑ 生成PPT (D)     │
                  │                                │ [确认][修改][取消] │
                  │                                └──────────────────┘
                  │
T+30s     ↩️      用户点击"确认"                    "已确认，开始执行"
                  confirmed = true
                  │
T+31s     C       生成文档大纲                      [场景C 运行中]
T+31s     D       生成 PPT 结构规划                 [场景D 运行中]  ← 同时开始!
                  │                                │
T+35s     C       输出: doc_outline                ┌──────────────────┐
                  │                                │ 📄 文档大纲确认    │
T+35s     ⏸️      暂停：等待用户确认大纲              │ # 会议纪要        │
                  │                                │ ## 讨论要点       │
T+36s     D       LLM 逐页内容精炼                  │ ## 决议事项       │
T+40s     D       python-pptx 渲染                 │ ## 待办事项       │
                  │                                │ [确认][修改]      │
T+45s     D       上传飞书云空间                    └──────────────────┘
T+50s     D       获取分享链接                      [场景D 完成 ✓]    ← D 先完成!
                  输出: ppt_url                     📊 PPT 已生成
                  广播: PPT 链接到客户端 + 飞书群     │
                  │                                │
T+60s     ↩️      用户确认文档大纲                   "正在生成文档内容..."
                  │                                │
T+61s     C       LLM 逐节展开内容                  [文档生成中 45%]
T+75s     C       创建飞书文档                      [文档生成中 80%]
T+80s     C       写入文档内容                      [场景C 完成 ✓]    ← C 后完成
                  输出: doc_url                     📄 文档已生成
                  广播: 文档链接到客户端 + 飞书群     │
                  │                                │
                  │  ┌── C 和 D 都已完成，触发 E ──┐ │
                  │                                │ │
T+81s     E       广播最终状态到所有客户端            [场景E 同步中]     │
                  确保所有端状态一致                  [场景E 完成 ✓]     │
                  │                                │
T+82s     F       汇总所有产出物                     [场景F 交付中]     │
T+85s     F       推送飞书消息（含所有链接）           [场景F 完成 ✓]     │
                  输出: delivery                    │
                  │                                │
T+85s     ✅      工作流结束                         ┌──────────────────┐
                                                  │ ✓ 全部完成        │
                                                  │ 📄 会议纪要 [查看] │
                                                  │ 📊 汇报PPT  [查看] │
                                                  │ [分享]            │
                                                  └──────────────────┘

总耗时: ~85s（串行需要 ~110s，节省 25s）
```

---

## 四、各场景内部工作流

### 4.1 场景 A：意图捕捉（内部 3 步）

```
输入: user_input (原始文本) + source (来源)
输出: intent (结构化意图) + chat_context (上下文)

Step A1: 文本预处理
─────────────────
  输入: user_input
  处理:
    · 去除 @Agent-Pilot 等 mention 标记
    · 去除多余空白和换行
    · 如果文本为空或太短（<5字），返回提示"请描述更详细的需求"
  输出: cleaned_text

Step A2: 上下文增强（仅飞书 IM 来源）
───────────────────────────────────────
  输入: cleaned_text + chat_id
  处理:
    · 调用飞书 API 拉取该群聊最近 50 条消息
    · 用 LLM 对历史消息做摘要（压缩到 500 字以内）
    · 将摘要作为 chat_context 附加
  输出: chat_context (摘要文本)
  注意: 如果来源是 H5，chat_context 为空

Step A3: LLM 意图识别
─────────────────────
  输入: cleaned_text + chat_context
  处理:
    · 调用豆包 LLM，使用 intent_recognition prompt
    · LLM 输出 JSON 格式的意图信息
    · 解析并校验 JSON 结构
  输出: intent {
    intent_type: "meeting_summary" | "weekly_report" | "doc_generation" |
                 "ppt_generation" | "custom",
    topic: "产品评审会议",
    key_points: ["用户增长策略", "技术架构升级", ...],
    confidence: 0.92
  }

  广播: 将 intent 结果推送到所有客户端
```

**意图类型与后续路径映射**：

```
intent_type ──────────────────► 决定场景 B 的规划策略

"meeting_summary"  ──►  branches: [C(文档), D(PPT)]  并列执行
"weekly_report"    ──►  branches: [C(文档), D(PPT)]  并列执行
"doc_generation"   ──►  branches: [C(文档)]           仅文档
"ppt_generation"   ──►  branches: [D(PPT)]            仅PPT
"custom"           ──►  LLM 自由决定 branches
```

---

### 4.2 场景 B：任务规划（内部 3 步）

```
输入: intent + chat_context
输出: task_plan (任务执行计划，含并列分支)

Step B1: LLM 任务拆解
─────────────────────
  输入: intent + chat_context
  处理:
    · 调用豆包 LLM，使用 task_planning prompt
    · Prompt 中明确告知 C 和 D 是并列关系
    · LLM 输出结构化的分支计划
  输出: task_plan {
    goal: "整理产品评审会议并生成汇报PPT",
    branches: [
      {
        scene: "C",
        action: "生成会议纪要文档",
        description: "从群聊记录中提取要点，生成结构化文档",
        trigger: true,
        need_outline_confirm: true
      },
      {
        scene: "D",
        action: "生成汇报PPT",
        description: "基于会议内容生成精炼的演示文稿",
        trigger: true,
        need_outline_confirm: false
      }
    ],
    post_actions: [
      { scene: "E", action: "多端同步" },
      { scene: "F", action: "总结交付" }
    ]
  }

Step B2: 计划合理性校验
───────────────────────
  处理:
    · 检查 branches 是否为空（至少要有一个）
    · 检查 post_actions 是否包含 E 和 F
    · 如果校验失败，让 LLM 重新规划（最多重试 2 次）
  输出: validated_task_plan

Step B3: 暂停等待用户确认
─────────────────────────
  处理:
    · 将 task_plan 格式化为用户可读的卡片/面板
    · 明确标注哪些分支会并行执行
    · 广播到所有客户端
    · 设置 need_confirm = true，暂停工作流
  输出: 等待用户输入

  用户操作分支:
  ┌──────────────────────────────────────────────┐
  │  "确认" ──► confirmed = true ──► 并行启动 C/D │
  │  "修改" ──► 用户输入修改意见                   │
  │           ──► 将意见附加到 state.messages      │
  │           ──► 回到 Step B1 重新规划            │
  │  "取消" ──► 工作流终止，状态设为 cancelled      │
  └──────────────────────────────────────────────┘
```

---

### 4.3 场景 C：文档生成（内部 5 步）

```
输入: task_plan + chat_context + intent（不依赖场景 D）
输出: doc_content + doc_url

Step C1: 文档大纲生成
─────────────────────
  输入: task_plan + chat_context + intent
  处理:
    · 调用 LLM，使用 doc_outline prompt
    · 根据意图类型选择不同的大纲模板
    · 输出结构化大纲（标题 + 各节标题 + 各节要点）
  输出: doc_outline {
    title: "产品评审会议纪要 - 2026.04.23",
    sections: [
      { heading: "会议概述", points: ["时间", "参会人", "议题"] },
      { heading: "讨论要点", points: ["用户增长策略", "技术架构升级"] },
      { heading: "决议事项", points: ["..."] },
      { heading: "待办事项", points: ["..."] }
    ]
  }

Step C2: 暂停等待用户确认大纲
─────────────────────────────
  处理:
    · 将 doc_outline 格式化为可读的大纲卡片
    · 广播到客户端
    · 设置 need_confirm = true
  用户操作:
    · "确认" ──► 继续
    · "修改" ──► 附加修改意见，回到 C1 重新生成大纲

Step C3: LLM 逐节展开内容
─────────────────────────
  输入: doc_outline + chat_context
  处理:
    · 遍历 doc_outline.sections
    · 对每个 section，调用 LLM 生成详细内容
    · 可以并行调用（多个 section 同时生成）
    · 每完成一个 section，广播进度更新
  输出: doc_content {
    title: "...",
    sections: [
      { heading: "会议概述", content: "本次会议于..." },
      { heading: "讨论要点", content: "1. 用户增长策略..." },
      ...
    ]
  }

Step C4: 创建飞书文档并写入
─────────────────────────────
  输入: doc_content
  处理:
    · 调用飞书 API 创建云文档
    · 按结构写入各节内容（标题 → 各节标题 → 各节正文）
    · 设置文档权限（创建者可编辑，相关人员可查看）
  输出: doc_url (飞书文档链接)

Step C5: 广播文档就绪
─────────────────────
  处理:
    · 广播 artifact_ready 消息到所有客户端
    · 如果来源是飞书 IM，发送卡片消息到群里（含文档链接）
```

**场景 C 内部数据流**：

```
task_plan + context
       │
       ▼
  [C1] LLM 生成大纲 ──► doc_outline
       │                      │
       │                      ▼
       │                [C2] 用户确认大纲
       │                      │
       │                 确认 ▼
       │              [C3] LLM 逐节展开 ──► doc_content
       │                      │
       │                      ▼
       │                [C4] 飞书 API 写入 ──► doc_url
       │                      │
       │                      ▼
       │                [C5] 广播通知
       │                      │
       ▼                      ▼
  (doc_outline + doc_content + doc_url 全部写入 State)
```

---

### 4.4 场景 D：PPT 生成（内部 5 步）

```
输入: task_plan + chat_context + intent（不依赖场景 C）
输出: ppt_content + ppt_url

Step D1: PPT 结构规划
─────────────────────
  输入: task_plan + chat_context + intent
  处理:
    · 调用 LLM，将上下文信息映射为 PPT 页面结构
    · 决定每页的标题、要点、备注
    · 选择合适的页面布局类型
  输出: ppt_structure {
    title: "产品评审汇报",
    slides: [
      { page: 1, type: "cover", title: "产品评审汇报", subtitle: "2026.04.23" },
      { page: 2, type: "agenda", title: "汇报大纲", points: ["讨论要点", "决议事项", "下一步计划"] },
      { page: 3, type: "content", title: "用户增长策略", points: [...], notes: "..." },
      { page: 4, type: "content", title: "技术架构升级", points: [...], notes: "..." },
      { page: 5, type: "summary", title: "总结与下一步", points: [...] },
      { page: 6, type: "ending", title: "谢谢" }
    ]
  }

Step D2: LLM 逐页内容精炼
─────────────────────────
  输入: ppt_structure + chat_context
  处理:
    · 对每页内容进行精炼（PPT 要点要简短有力）
    · 为每页生成演讲备注
    · 确保每页要点不超过 5 条，每条不超过 20 字
  输出: ppt_content (精炼后的完整 PPT 内容)

Step D3: python-pptx 渲染
──────────────────────────
  输入: ppt_content + 模板文件路径
  处理:
    · 加载 PPT 模板（商务/简约）
    · 按页面结构逐页渲染
    · 封面页 → 大纲页 → 内容页 → 总结页 → 结尾页
    · 每页写入标题、要点、备注
  输出: ppt_file_path (本地 .pptx 文件路径)

Step D4: 上传飞书云空间
───────────────────────
  输入: ppt_file_path
  处理:
    · 调用飞书文件上传 API
    · 上传到指定文件夹
    · 创建分享链接
  输出: ppt_url + ppt_share_url

Step D5: 广播 PPT 就绪
──────────────────────
  处理:
    · 广播 artifact_ready 到所有客户端
    · 如果来源是飞书 IM，发送卡片消息（含 PPT 链接）
```

**场景 C 和 D 的关键区别**：

| 维度 | 场景 C（文档） | 场景 D（PPT） |
|------|---------------|---------------|
| **输入来源** | intent + chat_context + task_plan | intent + chat_context + task_plan |
| **是否依赖对方** | ❌ 不依赖 D | ❌ 不依赖 C |
| **大纲确认** | ✅ 需要用户确认大纲 | ❌ 自动生成，不暂停 |
| **内容风格** | 详细、完整、可编辑 | 精炼、简短、可演示 |
| **输出位置** | 飞书云文档（在线可编辑） | 飞书云空间（.pptx 文件） |

---

### 4.5 场景 E：多端同步（汇合点）

**场景 E 是 C 和 D 的汇合节点。LangGraph 的并行边机制保证 E 只在所有已触发的分支完成后才执行。**

```
触发条件:
  · 如果 C 和 D 都触发了 → 两者都完成后才触发 E
  · 如果只触发了 C → C 完成后触发 E
  · 如果只触发了 D → D 完成后触发 E

同步内容:
─────────────────────────────────────────────────────
State 变更事件              同步到客户端的内容
─────────────────────────────────────────────────────
current_scene 变更          场景进度面板更新
scene_progress 变更         进度条/百分比更新
need_confirm = true         弹出确认交互卡片
artifact_ready              产出物卡片出现（可点击查看）
error 发生                  错误提示 + 重试按钮
workflow 完成               完成状态 + 所有产出物汇总
─────────────────────────────────────────────────────

实现机制:
  ┌──────────────────────────────────────────┐
  │  LangGraph State 变更                     │
  │       │                                   │
  │       ▼                                   │
  │  State 回调函数 (on_state_change)         │
  │       │                                   │
  │       ▼                                   │
  │  ConnectionManager.broadcast()            │
  │       │                                   │
  │       ├──► 飞书 H5 (WebSocket)            │
  │       └──► 飞书 IM (HTTP API 推送消息)    │
  └──────────────────────────────────────────┘
```

**场景 E 的"独立演示"模式**：

赛题要求各场景可独立演示。场景 E 的独立演示方式：
- 启动一个已有的工作流
- 在飞书桌面端和手机端 H5 同时打开
- 展示一端操作（如确认）→ 另一端实时更新

---

### 4.6 场景 F：总结与交付（内部 3 步）

```
输入: 已生成的所有产出物（doc_url / ppt_url，可能只有其中一个）
输出: delivery (交付物汇总)

Step F1: 汇总产出物
─────────────────────
  处理:
    · 收集所有已生成的 artifact
    · 生成工作流摘要（耗时、完成分支数等）
  输出: delivery {
    summary: "已完成产品评审会议纪要和汇报PPT的生成",
    artifacts: [
      { type: "doc", title: "产品评审会议纪要", url: "...", share_url: "..." },
      { type: "ppt", title: "产品评审汇报", url: "...", share_url: "..." }
    ],
    workflow_id: "wf_xxx",
    total_duration: "1m 25s",
    completed_branches: ["C", "D"],
    total_branches: 2
  }

  注意: 如果只有文档没有 PPT，artifacts 中只包含 doc

Step F2: 推送通知
─────────────────
  处理:
    · 如果来源是飞书 IM：
      发送飞书卡片消息，包含所有产出物链接
    · 广播 delivery 到所有客户端
    · 客户端展示完成面板

Step F3: 归档记录
─────────────────
  处理:
    · 将 workflow 状态更新为 completed
    · 持久化到数据库
    · 工作流结束
```

---

## 五、决策分支全景图

### 5.1 所有可能的分支路径

```
                              START
                                │
                                ▼
                          ┌──────────┐
                          │  场景 A   │
                          │  意图捕捉  │
                          └─────┬────┘
                                │
                    ┌───────────┼───────────┐
                    │           │           │
               confidence    confidence  confidence
               >= 0.7       0.3 ~ 0.7    < 0.3
                    │           │           │
                    ▼           ▼           ▼
               ┌────────┐  ┌────────┐  ┌────────┐
               │继续 B  │  │追问用户 │  │追问用户 │
               └───┬────┘  │补充信息 │  │重新描述 │
                   │       └───┬────┘  └───┬────┘
                   │           │           │
                   │     用户补充后 ──► 回到 A
                   │           │
                   ▼           ▼
                          ┌──────────┐
                          │  场景 B   │
                          │  任务规划  │
                          └─────┬────┘
                                │
                          ┌─────┴─────┐
                          │           │
                     need_confirm   need_confirm
                     = true        = false
                     (默认)        (简单任务)
                          │           │
                          ▼           │
                    ┌──────────┐     │
                    │ 用户确认  │     │
                    └─────┬────┘     │
                          │           │
               ┌──────────┼───────────┘
               │          │
          "确认"      "修改"
               │          │
               │     ┌────┴────┐
               │     │ 回到 B  │
               │     │ 重新规划 │
               │     └─────────┘
               │
          "取消" ──► END (cancelled)
               │
               ▼
     ┌─────────────────────────┐
     │  根据 branches 并行路由   │
     └────────┬────────┬───────┘
              │        │
         need_doc  need_ppt
              │        │
              ▼        ▼
     ┌──────────┐  ┌──────────┐
     │  场景 C   │  │  场景 D   │
     │  文档生成  │  │  PPT 生成  │
     └────┬─────┘  └────┬─────┘
          │              │
     ┌────┴────┐    ┌────┴────┐
     │大纲确认  │    │ 成功/失败│
     └────┬────┘    └────┬────┘
          │              │
     ┌────┼────┐    成功 ▼  失败
     │         │     ┌──────┐   │
   "确认"  "修改"   │(等待C)│   ▼
     │    回到C1     │      │ 跳过D
     ▼         ▼     │      │ (交付已有成果)
     └────┬────┘     │      │
          │          │      │
          │     ┌────┴──────┘
          │     │
          └─────┴──► 两者都完成后
                    │
                    ▼
              ┌──────────┐
              │  场景 E   │
              │  多端同步  │
              └─────┬────┘
                    │
                    ▼
              ┌──────────┐
              │  场景 F   │
              │  总结交付  │
              └─────┬────┘
                    │
                    ▼
              END (completed)
```

### 5.2 异常处理分支

```
异常类型                    处理方式
──────────────────────────────────────────────────────────────
LLM 调用超时                重试（最多 2 次，指数退避）
                           持续失败 → 通知用户 "AI 服务暂时不可用"

LLM 返回格式错误            重试（附加格式修正提示）
                           持续失败 → 使用默认模板兜底

飞书 API 调用失败           重试（最多 3 次）
                           持续失败 → 跳过该分支，记录错误
                           例：文档创建失败 → C 分支失败，D 继续执行

python-pptx 渲染失败       记录错误日志
                           通知用户 "PPT 生成失败，文档已生成"
                           D 分支失败不影响 C，E 在 C 完成后触发

C 和 D 同时失败            通知用户 "生成失败"
                           工作流直接到 F（交付空结果 + 错误信息）

WebSocket 连接断开          客户端自动重连（指数退避，最大 30s）
                           重连后拉取最新状态（HTTP API 补偿）

用户长时间不确认            超时提醒（5 分钟后发送提醒）
                           30 分钟后自动取消工作流

工作流执行中途取消          清理已创建的资源（可选）
                           记录工作流状态为 cancelled
                           通知所有客户端
```

**并列架构的容错优势**：

```
串行时：C 失败 → D 无法执行 → 全部失败
并列时：C 失败 → D 照常执行 → 用户至少能拿到 PPT
       D 失败 → C 照常执行 → 用户至少能拿到文档
```

---

## 六、场景组合模式

赛题要求"各场景可独立成立并单独演示，也可按需求自由组合编排"。

### 6.1 预设组合模式

```
模式 1: 完整链路（默认）
────────────────────
A → B ─┬→ C ─┬→ E → F
       └→ D ─┘
适用: 用户首次使用，完整体验
触发: "帮我整理会议纪要并生成汇报PPT"

模式 2: 仅文档生成
────────────────────
A → B(branches=[C]) → C → E → F
适用: 用户只需要文档
触发: intent_type = "doc_generation" 或 "帮我生成文档"

模式 3: 仅 PPT 生成
────────────────────
A → B(branches=[D]) → D → E → F
适用: 用户只需要PPT
触发: intent_type = "ppt_generation" 或 "帮我做一份PPT"

模式 4: 快速模式（跳过确认）
────────────────────
A → B ─┬→ C(跳过大纲确认) ─┬→ E → F
       └→ D ───────────────┘
适用: 简单任务，不需要逐步确认
触发: 用户指令中包含"快速"、"简单"等关键词

模式 5: 交互式深度模式
────────────────────
A → B → C(确认大纲+确认内容) + D(确认PPT结构) → E → F
适用: 重要任务，需要每步确认
触发: 用户指令中包含"详细"、"仔细"等关键词
```

### 6.2 场景 B 的规划策略（根据意图动态调整）

```
场景 B 根据 intent_type 决定生成哪些并列分支:

intent_type = "meeting_summary":
  branches = [C(生成纪要文档), D(生成汇报PPT)]

intent_type = "weekly_report":
  branches = [C(生成周报文档), D(生成汇报PPT)]

intent_type = "doc_generation":
  branches = [C(生成文档)]

intent_type = "ppt_generation":
  branches = [D(生成PPT)]

intent_type = "custom":
  branches = [LLM 自由决定]
```

### 6.3 独立演示模式

每个场景都可以脱离完整链路独立运行：

```
场景 A 独立演示:
  输入一段文本 → 展示意图识别结果
  演示重点: LLM 理解能力

场景 B 独立演示:
  给定一个意图 → 展示任务规划结果（含并列分支）
  演示重点: 任务拆解和规划能力

场景 C 独立演示:
  给定一个任务 → 生成飞书文档
  演示重点: 文档生成质量和飞书集成

场景 D 独立演示:
  给定上下文信息 → 生成 PPT
  演示重点: PPT 生成质量和模板效果

场景 E 独立演示:
  打开多个客户端 → 触发状态变更 → 观察同步效果
  演示重点: 多端实时同步

场景 F 独立演示:
  给定已有产出物 → 展示交付效果
  演示重点: 交付物整理和通知
```

---

## 七、LangGraph 编排映射

### 7.1 图结构定义

```python
# 节点清单
nodes = {
    "scene_a":     scene_a_node,        # 意图捕捉
    "scene_b":     scene_b_node,        # 任务规划
    "scene_c":     scene_c_node,        # 文档生成
    "scene_d":     scene_d_node,        # PPT 生成
    "scene_e":     scene_e_node,        # 多端同步（汇合点）
    "scene_f":     scene_f_node,        # 总结交付
    "confirm":     confirm_node,        # 通用确认等待节点
    "error":       error_node,          # 错误处理节点
}

# 边清单
edges = {
    # 主流程
    START              → scene_a,
    scene_a            → scene_b,

    # B → 确认 → 并行路由
    scene_b            → confirm,                    # 默认: 需要确认
    confirm(approved)  → route_branches,             # 根据计划决定并行分支
    confirm(modified)  → scene_b,                    # 修改后重新规划
    confirm(cancelled) → END,

    # 并行分支（LangGraph 并行边）
    route_branches(both)    → ["scene_c", "scene_d"],  # C 和 D 并行
    route_branches(doc_only) → scene_c,                # 仅 C
    route_branches(ppt_only) → scene_d,                # 仅 D

    # C 和 D 都汇入 E（LangGraph 自动等待所有前驱完成）
    scene_c            → scene_e,
    scene_d            → scene_e,

    # E → F → END
    scene_e            → scene_f,
    scene_f            → END,

    # 错误处理
    error(retry)       → previous_node,              # 重试
    error(skip)        → scene_e,                    # 跳过当前分支，直接汇合
    error(fatal)       → scene_f,                    # 直接交付已有成果
}
```

### 7.2 条件路由函数

```python
def route_branches(state: IMState) -> str:
    """根据任务计划决定执行哪些并行分支"""
    plan = state["task_plan"]
    branches = plan.get("branches", [])

    need_doc = any(b["scene"] == "C" and b["trigger"] for b in branches)
    need_ppt = any(b["scene"] == "D" and b["trigger"] for b in branches)

    if need_doc and need_ppt:
        return "both"         # 并行执行 C 和 D
    elif need_doc:
        return "doc_only"     # 只执行 C
    elif need_ppt:
        return "ppt_only"     # 只执行 D
    else:
        return "doc_only"     # 兜底：至少生成文档


def should_confirm(state: IMState) -> str:
    """判断是否需要人工确认"""
    if state.get("need_confirm", False):
        return "confirm"
    return "skip"


def handle_confirm(state: IMState) -> str:
    """处理用户确认结果"""
    if state.get("confirmed", False):
        return "approved"
    elif state.get("cancelled", False):
        return "cancelled"
    else:
        return "modified"
```

### 7.3 LangGraph 完整实现骨架

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator


class IMState(TypedDict):
    """Agent 全局状态"""
    # 基础信息
    workflow_id: str
    user_id: str
    user_input: str
    source: str

    # 场景 A 输出
    intent: dict
    chat_context: str

    # 场景 B 输出
    task_plan: dict

    # 场景 C 输出（独立于 D）
    doc_outline: dict
    doc_content: dict
    doc_url: str

    # 场景 D 输出（独立于 C）
    ppt_structure: dict
    ppt_content: dict
    ppt_url: str

    # 场景 F 输出
    delivery: dict

    # 控制流
    messages: Annotated[list, operator.add]
    current_scene: str
    need_confirm: bool
    confirmed: bool
    cancelled: bool
    error: str | None


def build_graph() -> StateGraph:
    graph = StateGraph(IMState)

    # 添加节点
    graph.add_node("scene_a", scene_a_node)
    graph.add_node("scene_b", scene_b_node)
    graph.add_node("scene_c", scene_c_node)
    graph.add_node("scene_d", scene_d_node)
    graph.add_node("scene_e", scene_e_node)
    graph.add_node("scene_f", scene_f_node)
    graph.add_node("confirm", confirm_node)

    # 定义边
    graph.set_entry_point("scene_a")
    graph.add_edge("scene_a", "scene_b")

    # B → 确认 → 并行路由
    graph.add_conditional_edges("scene_b", should_confirm, {
        "confirm": "confirm",
        "skip": "route_branches"
    })
    graph.add_conditional_edges("confirm", handle_confirm, {
        "approved": "route_branches",
        "modified": "scene_b",
        "cancelled": END
    })

    # ★ 核心：并行分支路由
    graph.add_conditional_edges("route_branches", route_branches, {
        "both":      ["scene_c", "scene_d"],   # 并行！
        "doc_only":  "scene_c",
        "ppt_only":  "scene_d"
    })

    # C 和 D 汇入 E（LangGraph 自动等待两者都完成）
    graph.add_edge("scene_c", "scene_e")
    graph.add_edge("scene_d", "scene_e")

    # E → F → END
    graph.add_edge("scene_e", "scene_f")
    graph.add_edge("scene_f", END)

    return graph.compile()
```

---

## 八、用户交互时序图

### 8.1 完整交互时序（飞书 IM 入口，C/D 并行）

```
用户          飞书App       Agent后端         豆包LLM        飞书API       H5客户端
 │              │              │                │              │              │
 │ @bot 整理会议 │              │                │              │              │
 │─────────────►│              │                │              │              │
 │              │ 事件回调      │                │              │              │
 │              │─────────────►│                │              │              │
 │              │              │                │              │              │
 │              │              │ 意图识别        │              │              │
 │              │              │───────────────►│              │              │
 │              │              │◄───────────────│              │              │
 │              │              │                │              │              │
 │              │              │ 拉取群聊历史    │              │              │
 │              │              │──────────────────────────────►│              │
 │              │              │◄──────────────────────────────│              │
 │              │              │                │              │              │
 │              │              │ 任务规划        │              │              │
 │              │              │───────────────►│              │              │
 │              │              │◄───────────────│              │              │
 │              │              │                │              │  状态推送     │
 │              │              │──────────────────────────────────────────────►│
 │              │              │                │              │              │
 │  收到确认卡片  │              │                │              │              │
 │◄─────────────│              │                │              │              │
 │              │              │                │              │              │
 │  点击"确认"   │              │                │              │              │
 │─────────────►│              │                │              │              │
 │              │ 卡片回调      │                │              │              │
 │              │─────────────►│                │              │              │
 │              │              │                │              │              │
 │              │              │ ┌─ 并行开始 ──┐ │              │              │
 │              │              │ │             │ │              │              │
 │              │              │ │ 生成文档大纲 │ │              │              │
 │              │              │ │────────────►│ │              │              │
 │              │              │ │◄────────────│ │              │              │
 │              │              │ │             │ │              │  C+D并行中   │
 │              │              │ │ 生成PPT结构 │ │              │──────────────►│
 │              │              │ │────────────►│ │              │              │
 │              │              │ │◄────────────│ │              │              │
 │              │              │ │             │ │              │              │
 │  收到大纲卡片  │              │ │             │ │              │              │
 │◄─────────────│              │ │             │ │              │              │
 │              │              │ │             │ │              │              │
 │              │              │ │ PPT逐页精炼 │ │              │              │
 │              │              │ │────────────►│ │              │              │
 │              │              │ │◄────────────│ │              │              │
 │              │              │ │             │ │              │              │
 │              │              │ │ PPT渲染+上传│ │              │              │
 │              │              │ │───────────────────────────►│              │
 │              │              │ │◄───────────────────────────│              │
 │              │              │ │             │ │              │              │
 │              │              │ │ PPT就绪!   │ │              │  PPT已生成   │
 │              │              │ │             │ │              │──────────────►│
 │              │              │ └─────────────┘ │              │              │
 │              │              │                │              │              │
 │  点击"确认大纲"│              │                │              │              │
 │─────────────►│              │                │              │              │
 │              │─────────────►│                │              │              │
 │              │              │                │              │              │
 │              │              │ 逐节生成内容    │              │              │
 │              │              │───────────────►│              │              │
 │              │              │◄───────────────│              │              │
 │              │              │                │              │              │
 │              │              │ 创建文档        │              │              │
 │              │              │──────────────────────────────►│              │
 │              │              │◄──────────────────────────────│              │
 │              │              │                │              │              │
 │              │              │ 文档就绪!      │              │  文档已生成   │
 │              │              │                │              │──────────────►│
 │              │              │                │              │              │
 │              │              │ ── C和D都完成，触发E ──│              │              │
 │              │              │                │              │              │
 │              │              │ 汇总+推送交付   │              │  全部完成     │
 │              │              │                │              │──────────────►│
 │              │              │                │              │              │
 │  收到交付卡片  │              │                │              │              │
 │◄─────────────│              │                │              │              │
 │  (含文档+PPT链接)            │                │              │              │
 │              │              │                │              │              │
```

---

## 九、状态广播协议（客户端视角）

### 9.1 客户端收到消息的完整序列

```
# 完整链路中，客户端会依次收到以下 WebSocket 消息:

1.  workflow_created         # 新工作流创建
2.  scene_started (A)        # 场景 A 开始
3.  scene_completed (A)      # 场景 A 完成
4.  scene_started (B)        # 场景 B 开始
5.  scene_completed (B)      # 场景 B 完成
6.  confirm_required         # 需要用户确认任务计划

    -- 用户操作后 --

7.  confirm_result           # 确认结果

8.  scene_started (C)        # 场景 C 开始 ★
9.  scene_started (D)        # 场景 D 开始 ★（几乎同时）

10. scene_progress (D)       # PPT 进度（D 通常更快）
11. artifact_ready (ppt)     # PPT 就绪 ★ D 先完成
12. scene_completed (D)

13. confirm_required         # 文档大纲确认（C 需要用户确认）

    -- 用户操作后 --

14. confirm_result

15. scene_progress (C)       # 文档内容生成进度
16. artifact_ready (doc)     # 文档就绪 ★ C 后完成
17. scene_completed (C)

18. scene_started (E)        # ★ C 和 D 都完成后才触发 E
19. scene_completed (E)

20. scene_started (F)
21. scene_completed (F)

22. workflow_completed       # 工作流完成
```

### 9.2 客户端状态机

```
客户端根据收到的消息更新 UI 状态:

IDLE ──(workflow_created)──► RUNNING
RUNNING ──(scene_started)──► 更新当前场景高亮（支持多个场景同时高亮）
RUNNING ──(scene_progress)──► 更新对应场景的进度条
RUNNING ──(confirm_required)──► 弹出确认面板
RUNNING ──(artifact_ready)──► 显示产出物卡片（可逐个出现）
RUNNING ──(workflow_completed)──► COMPLETED
RUNNING ──(error)──► ERROR (显示重试按钮)
ERROR ──(retry)──► RUNNING
COMPLETED ──(新 workflow_created)──► RUNNING
```

**并列架构下客户端的特殊处理**：
- 进度面板需要同时展示 C 和 D 的进度（两个进度条并行）
- 产出物卡片逐个出现（D 先完成显示 PPT 卡片，C 后完成显示文档卡片）
- 场景高亮支持多个（C 和 D 同时高亮为"运行中"）

---

## 十、一句话总结每个场景

| 场景 | 一句话 | 输入 → 输出 |
|------|--------|-------------|
| **A** | 听懂用户要什么 | 原始文本 → 结构化意图 |
| **B** | 想好怎么做（决定哪些分支） | 意图 → 并列分支计划 |
| **C** | 写出文档（独立于 D） | 计划+上下文 → 飞书文档链接 |
| **D** | 做出 PPT（独立于 C） | 计划+上下文 → 飞书 PPT 链接 |
| **E** | 等齐后同步（C/D 汇合点） | 所有分支完成 → 多端状态同步 |
| **F** | 交付成果 | 所有链接 → 通知+归档 |
