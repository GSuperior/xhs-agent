"""所有 LLM Agent 的基类。Controller 不是 Agent，是确定性 Python 代码。"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..tools.llm_client import LLMClient, LLMResponse
from ..tools.logger import DecisionLogger
from ..tools.artifact_store import ArtifactStore


class BaseAgent(ABC):
    """所有 LLM Agent 的基类。Controller 不是 Agent，是确定性 Python 代码。"""

    def __init__(
        self,
        llm: LLMClient,
        logger: DecisionLogger,
        store: ArtifactStore,
        model: str = "sensenova-6.7-flash-lite",
    ):
        self.llm = llm
        self.logger = logger
        self.store = store
        self.model = model

    @abstractmethod
    def get_system_prompt(self) -> str:
        """返回 Agent 的系统提示词。"""

    def _build_messages(self, user_content: str, context: str = "") -> list:
        msgs = [{"role": "system", "content": self.get_system_prompt()}]
        if context:
            msgs.append({"role": "system", "content": f"上下文:\n{context}"})
        msgs.append({"role": "user", "content": user_content})
        return msgs

    def _log(
        self,
        run_id,
        stage,
        agent_name,
        input_refs,
        output_ref,
        llm_resp,
        decision,
        reasons,
        warnings=None,
    ):
        self.logger.log(
            run_id,
            stage,
            agent_name,
            input_refs,
            output_ref,
            llm_resp.model,
            llm_resp.duration_ms,
            llm_resp.usage,
            decision,
            reasons,
            warnings,
        )
