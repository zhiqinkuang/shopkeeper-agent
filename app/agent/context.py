"""问数智能体运行上下文定义"""

from dataclasses import dataclass, field
from datetime import date

from langchain_core.embeddings import Embeddings

from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


@dataclass
class DataAgentContext:
    """单次图运行使用且不写入共享状态的工具与配置"""

    column_qdrant_repository: ColumnQdrantRepository
    embedding_client: Embeddings
    metric_qdrant_repository: MetricQdrantRepository
    value_es_repository: ValueESRepository
    meta_mysql_repository: MetaMySQLRepository
    dw_mysql_repository: DWMySQLRepository
    current_date: date = field(default_factory=date.today)
    max_correction_attempts: int = 2
    simulated_validation_failures: int = 0
