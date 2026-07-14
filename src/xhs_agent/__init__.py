"""xhs_agent — 小红书 AI 内容 Agent 产前闭环。

导出:
- Config / config: 配置加载器
- Controller: 确定性状态机
- 6 个 LLM Agent: DiscoveryAgent, ResearchAgent, PlanningAgent, WritingAgent, VisualAgent, ReviewerAgent
- app / XHSAgent: CLI 入口
"""

from .config import Config, config
from .controller import Controller
from .agents import (
    BaseAgent,
    DiscoveryAgent,
    DiscoveryCandidates,
    ResearchAgent,
    PlanningAgent,
    WritingAgent,
    VisualAgent,
    VisualPlan,
    ReviewerAgent,
)
from .cli import app, XHSAgent

__all__ = [
    # config
    "Config",
    "config",
    # controller
    "Controller",
    # agents
    "BaseAgent",
    "DiscoveryAgent",
    "DiscoveryCandidates",
    "ResearchAgent",
    "PlanningAgent",
    "WritingAgent",
    "VisualAgent",
    "VisualPlan",
    "ReviewerAgent",
    # cli
    "app",
    "XHSAgent",
]
