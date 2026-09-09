"""配置中心：统一从 .env / 环境变量读取全部配置。"""
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    # ---- LLM（OpenAI 兼容）----
    llm_api_key: str = field(default_factory=lambda: _get("LLM_API_KEY"))
    llm_base_url: str = field(default_factory=lambda: _get("LLM_BASE_URL", "https://api.deepseek.com/v1"))
    llm_model: str = field(default_factory=lambda: _get("LLM_MODEL", "deepseek-chat"))
    llm_temperature: float = 0.3
    # 无 Key 时自动进入离线演示模式
    @property
    def offline(self) -> bool:
        return not self.llm_api_key

    # ---- Embedding（OpenAI 兼容）----
    embed_api_key: str = field(default_factory=lambda: _get("EMBED_API_KEY"))
    embed_base_url: str = field(default_factory=lambda: _get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1"))
    embed_model: str = field(default_factory=lambda: _get("EMBED_MODEL", "BAAI/bge-m3"))
    embed_dim: int = int(_get("EMBED_DIM", "1024"))

    # ---- 基础设施 ----
    milvus_host: str = field(default_factory=lambda: _get("MILVUS_HOST", "localhost"))
    milvus_port: int = int(_get("MILVUS_PORT", "19530"))
    redis_host: str = field(default_factory=lambda: _get("REDIS_HOST", "localhost"))
    redis_port: int = int(_get("REDIS_PORT", "6379"))
    redis_db: int = int(_get("REDIS_DB", "0"))
    mysql_host: str = field(default_factory=lambda: _get("MYSQL_HOST", "localhost"))
    mysql_port: int = int(_get("MYSQL_PORT", "3306"))
    mysql_user: str = field(default_factory=lambda: _get("MYSQL_USER", "root"))
    mysql_password: str = field(default_factory=lambda: _get("MYSQL_PASSWORD", "root"))
    mysql_db: str = field(default_factory=lambda: _get("MYSQL_DB", "store_agent"))

    # ---- 监控告警 ----
    feishu_webhook: str = field(default_factory=lambda: _get("FEISHU_WEBHOOK"))
    alert_error_rate: float = float(_get("ALERT_ERROR_RATE", "0.05"))
    alert_latency_ms: float = float(_get("ALERT_LATENCY_MS", "3000"))

    # ---- 企业微信 ----
    wecom_token: str = field(default_factory=lambda: _get("WECOM_TOKEN", "storeagent"))
    wecom_webhook: str = field(default_factory=lambda: _get("WECOM_WEBHOOK"))  # 维修群机器人，报修工单创建即推送

    # ---- 路径 ----
    project_dir: Path = Path(__file__).resolve().parents[1]
    data_dir: Path = project_dir / "data"
    raw_docs_dir: Path = data_dir / "raw_docs"
    index_path: Path = data_dir / "index.json"


settings = Settings()
