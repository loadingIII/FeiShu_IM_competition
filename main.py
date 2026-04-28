import uuid
import asyncio
from graph.graph import build_workflow


# 示例运行代码
if __name__ == "__main__":
    # 初始化工作流
    workflow = build_workflow()
    
    # 初始状态
    initial_state = {
        "workflow_id": str(uuid.uuid4()),
        "user_id": "user_123",
        "user_input": "@Agent-Pilot 帮我准备一下明天的会议材料,主题是'AI在医疗领域的应用',需要包含PPT和文档",
        "source": "feishu_im",
        "chat_id": "oc_81881e331cd9d7f921771aa884b96742",
        "intent": None,
        "chat_context": "",
        "task_plan": None,
        "doc_outline": None,
        "doc_content": None,
        "doc_url": "",
        "ppt_structure": None,
        "ppt_content": None,
        "ppt_url": "",
        "delivery": None,
        "messages": [],
        "current_scene": "",
        "need_confirm": False,
        "confirmed": False,  # 等待用户确认
        "cancelled": False,
        "error": None
    }
    
    # 运行工作流
    async def run_workflow():
        # 直接获取最终结果
        result = await workflow.ainvoke(initial_state)
        
        # 去重打印日志（保持顺序）
        seen = set()
        unique_messages = []
        for msg in result["messages"]:
            if msg not in seen:
                unique_messages.append(msg)
                seen.add(msg)
        
        print("执行日志:")
        for msg in unique_messages:
            print(f"  {msg}")
        
        print("\n=== 工作流执行完成 ===")
        print(f"工作流ID: {result['workflow_id']}")
        print(f"最终状态: {result['current_scene']}")
        print("\n产出物:")
        delivery = result.get("delivery")
        if delivery and "artifacts" in delivery:
            for artifact in delivery["artifacts"]:
                print(f"- {artifact['title']}: {artifact['url']}")
        else:
            print("- 无产出物（工作流可能未执行到交付环节）")
    
    asyncio.run(run_workflow())
