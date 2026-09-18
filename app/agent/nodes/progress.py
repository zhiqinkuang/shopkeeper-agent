"""节点进度消息"""

from typing import Literal

ProgressStatus = Literal["running", "success", "error"]


def progress_event(step: str, status: ProgressStatus) -> dict[str, str]:
    """构造前端约定的 progress 消息"""
    return {"type": "progress", "step": step, "status": status}
