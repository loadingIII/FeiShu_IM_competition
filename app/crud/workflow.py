import asyncio
from typing import Optional, Dict, List
from app.model import WorkflowInstance


class WorkflowCRUD:
    """工作流数据访问层"""

    def __init__(self):
        self._instances: Dict[str, WorkflowInstance] = {}
        self._lock = asyncio.Lock()

    async def get(self, workflow_id: str) -> Optional[WorkflowInstance]:
        """获取工作流实例"""
        async with self._lock:
            return self._instances.get(workflow_id)

    async def create(self, workflow_id: str, instance: WorkflowInstance) -> WorkflowInstance:
        """创建工作流实例"""
        async with self._lock:
            self._instances[workflow_id] = instance
        return instance

    async def update(self, workflow_id: str, instance: WorkflowInstance) -> Optional[WorkflowInstance]:
        """更新工作流实例"""
        async with self._lock:
            if workflow_id in self._instances:
                self._instances[workflow_id] = instance
                return instance
            return None

    async def delete(self, workflow_id: str) -> bool:
        """删除工作流实例"""
        async with self._lock:
            if workflow_id in self._instances:
                del self._instances[workflow_id]
                return True
            return False

    async def list_all(self, limit: int = 20) -> List[WorkflowInstance]:
        """列出工作流实例"""
        async with self._lock:
            sorted_instances = sorted(
                self._instances.values(),
                key=lambda x: x.created_at,
                reverse=True,
            )
            return sorted_instances[:limit]


workflow_crud = WorkflowCRUD()
