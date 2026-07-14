"""xhs_agent 工具层：确定性工具（非 LLM Agent）。

包含：
- llm_client: LLM 客户端（OpenAI 兼容 / SenseNova）
- fetch: 网页抓取（SSRF 防护 + Prompt Injection 防护 + 来源快照）
- validators: Schema / Reference / Render 三个确定性校验器
- renderer: Jinja2 HTML 渲染 + Playwright PNG 截图
- artifact_store: Artifact 版本化存储
- logger: 决策级日志记录器
"""

from .llm_client import LLMClient, LLMResponse
from .fetch import FetchError, FetchResult, Fetcher
from .validators import (
    ReferenceValidator,
    RenderValidator,
    SchemaValidator,
    ValidationResult,
)
from .renderer import Renderer, render_card_html, render_html, render_png
from .artifact_store import ArtifactStore
from .logger import DecisionLogger

__all__ = [
    # llm_client
    "LLMClient",
    "LLMResponse",
    # fetch
    "FetchError",
    "FetchResult",
    "Fetcher",
    # validators
    "ReferenceValidator",
    "RenderValidator",
    "SchemaValidator",
    "ValidationResult",
    # renderer
    "Renderer",
    "render_card_html",
    "render_html",
    "render_png",
    # artifact_store
    "ArtifactStore",
    # logger
    "DecisionLogger",
]
