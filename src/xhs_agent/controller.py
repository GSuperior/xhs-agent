"""确定性 Controller（状态机）。

这是确定性 Python 代码，不是 LLM Agent。
负责状态机流转、确认节点、失败回退、日志、重试预算管理。
"""

import os

from .schemas.common import RunState
from .tools.llm_client import LLMClient
from .tools.logger import DecisionLogger
from .tools.artifact_store import ArtifactStore


class Controller:
    """确定性状态机 Controller。不是 LLM Agent。"""

    def __init__(
        self,
        llm: LLMClient = None,
        runs_dir: str = "./runs",
        log_dir: str = "./logs",
    ):
        self.llm = llm or LLMClient()
        self.logger = DecisionLogger(log_dir)
        self.store = ArtifactStore(runs_dir)
        self.state = RunState.INIT
        self.run_id = None
        self.research_count = 0
        self.outline_revise_count = 0
        self.copy_revise_count = 0
        self.layout_revise_count = 0
        self.render_retry_count = 0
        # 从 .env 读预算
        self.max_research = int(os.getenv("MAX_SUPPLEMENT_RESEARCH", "1"))
        self.max_outline = int(os.getenv("MAX_REVISE_OUTLINE", "2"))
        self.max_copy = int(os.getenv("MAX_REVISE_COPY", "2"))
        self.max_layout = int(os.getenv("MAX_REVISE_LAYOUT", "2"))
        self.max_render = int(os.getenv("MAX_RENDER_RETRY", "2"))

    def start(self, topic: str) -> str:
        self.run_id = self.store.create_run(topic)
        self.state = RunState.DISCOVERING
        return self.run_id

    def transition(self, new_state: RunState):
        old = self.state
        self.state = new_state
        return f"{old.value} -> {new_state.value}"

    def can_research(self) -> bool:
        return self.research_count < self.max_research

    def can_revise_outline(self) -> bool:
        return self.outline_revise_count < self.max_outline

    def can_revise_copy(self) -> bool:
        return self.copy_revise_count < self.max_copy

    def can_revise_layout(self) -> bool:
        return self.layout_revise_count < self.max_layout

    def can_render(self) -> bool:
        return self.render_retry_count < self.max_render

    def handle_reviewer_result(self, result) -> RunState:
        """根据 ReviewerResult 路由到下一个状态。"""
        from .schemas.common import ReviewStatus

        if result.status == ReviewStatus.PASS:
            return self._next_after_review()
        elif result.status == ReviewStatus.FAILED:
            return RunState.FAILED
        elif result.status == ReviewStatus.BLOCKED:
            return RunState.HUMAN_REVIEW
        elif result.status == ReviewStatus.REVISE:
            return self._route_revise(result.route_to)
        return RunState.HUMAN_REVIEW

    def _next_after_review(self) -> RunState:
        """审核通过后的下一个状态，根据当前状态决定。"""
        flow = {
            RunState.EVIDENCE_REVIEW: RunState.OUTLINING,
            RunState.CONTENT_REVIEW: RunState.VISUAL_PLANNING,
            RunState.LAYOUT_REVIEW: RunState.RENDERING,
        }
        return flow.get(self.state, RunState.HUMAN_REVIEW)

    def _route_revise(self, route_to: str) -> RunState:
        mapping = {
            "researching": RunState.RESEARCHING,
            "outlining": RunState.OUTLINING,
            "drafting": RunState.DRAFTING,
            "visual_planning": RunState.VISUAL_PLANNING,
            "rendering": RunState.RENDERING,
        }
        target = mapping.get(route_to)
        if target == RunState.RESEARCHING:
            if not self.can_research():
                return RunState.HUMAN_REVIEW
            self.research_count += 1
        elif target == RunState.OUTLINING:
            if not self.can_revise_outline():
                return RunState.HUMAN_REVIEW
            self.outline_revise_count += 1
        elif target == RunState.DRAFTING:
            if not self.can_revise_copy():
                return RunState.HUMAN_REVIEW
            self.copy_revise_count += 1
        elif target == RunState.VISUAL_PLANNING:
            if not self.can_revise_layout():
                return RunState.HUMAN_REVIEW
            self.layout_revise_count += 1
        return target or RunState.HUMAN_REVIEW

    def handle_human_review(self, action: str) -> RunState:
        """处理 HUMAN_REVIEW 恢复路由。"""
        routes = {
            "supplement_source": RunState.RESEARCHING,
            "accept_limitation": RunState.OUTLINING,
            "fix_asset": RunState.RENDERING,
            "accept_limited_final": RunState.FINAL_CONFIRMATION,
            "terminate": RunState.FAILED,
        }
        return routes.get(action, RunState.FAILED)

    def is_terminal(self) -> bool:
        return self.state in (RunState.COMPLETED, RunState.FAILED)

    def get_state_info(self) -> dict:
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "research_count": self.research_count,
            "outline_revise_count": self.outline_revise_count,
            "copy_revise_count": self.copy_revise_count,
            "layout_revise_count": self.layout_revise_count,
            "render_retry_count": self.render_retry_count,
        }
