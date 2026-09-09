"""问数智能体运行上下文定义"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class QueryContext:
    """单次图运行使用且不写入共享状态的配置"""

    current_date: date = field(default_factory=date.today)
    max_correction_attempts: int = 2
    simulated_validation_failures: int = 0
