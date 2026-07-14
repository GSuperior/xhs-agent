"""Reviewer Agent。

职责：语义和质量判断、错误路由建议。不直接改写产物。
输入：根据模式不同
  - evidence 模式：evidence_pack
  - content 模式：card_outline + evidence_pack
  - layout 模式：layout_spec + draft
输出：ReviewerResult（status/issue_type/route_to/issues/severity）
"""

from typing import Optional

from ..schemas.common import ReviewerMode
from ..schemas.content import CardOutline, Draft
from ..schemas.evidence import EvidencePack
from ..schemas.review import ReviewerResult
from ..schemas.visual import LayoutSpec
from .base import BaseAgent


class ReviewerAgent(BaseAgent):
    """Reviewer Agent，三模式语义审核。不直接改写产物。"""

    def get_system_prompt(self) -> str:
        return """你是 Reviewer Agent，负责语义和质量判断，不直接改写产物。

## 通用规则
1. 每个问题（issue）必须带 rule_id（如 CONTENT_003）、location、problem、severity、suggested_action。
2. status=pass 时 issue_type 和 route_to 必须为 null。issues 通常为空；但允许携带 severity=minor 的信息性 warning（如 LLM 知识模式下的 EVIDENCE_007），用于记录不影响通过的非阻断提示。
3. status=revise 时 route_to 必须在白名单内：researching / outlining / drafting / visual_planning / rendering / human_review / failed。
4. status=failed 时 severity 必须为 blocking，仅用于不可恢复问题（严重事实错误、机密泄露、安全风险）。
5. severity 枚举：none / minor / major / blocking。

## 状态语义
- pass：通过，进入下一阶段。
- revise：需返工，route_to 指定回退目标。
- blocked：需人工介入（HUMAN_REVIEW）。
- failed：不可恢复，终止。

## issue_type 枚举
evidence / outline / copy / layout / render / safety

只输出 JSON，不要额外解释。"""

    def execute(
        self,
        run_id: str,
        mode: ReviewerMode,
        evidence_pack: Optional[EvidencePack] = None,
        card_outline: Optional[CardOutline] = None,
        draft: Optional[Draft] = None,
        layout_spec: Optional[LayoutSpec] = None,
    ) -> ReviewerResult:
        """根据模式审核产物，返回 ReviewerResult。"""
        mode_prompt = self._get_mode_prompt(mode)
        context = self._build_context(mode, evidence_pack, card_outline, draft, layout_spec)
        user_content = (
            f"当前审核模式：{mode.value}\n\n"
            f"{mode_prompt}\n\n"
            f"请审核上述产物，输出 ReviewerResult JSON。"
        )

        msgs = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "system", "content": f"上下文:\n{context}"},
            {"role": "user", "content": user_content},
        ]

        result, llm_resp = self.llm.chat_json(
            self.model, msgs, ReviewerResult
        )

        stage_map = {
            ReviewerMode.EVIDENCE: "EVIDENCE_REVIEW",
            ReviewerMode.CONTENT: "CONTENT_REVIEW",
            ReviewerMode.LAYOUT: "LAYOUT_REVIEW",
        }
        stage = stage_map.get(mode, "REVIEW")

        version = self.store.get_latest_version(run_id, f"reviewer_{mode.value}") + 1
        output_ref = self.store.save_artifact(
            run_id, f"reviewer_{mode.value}", result.model_dump(), version
        )

        self._log(
            run_id=run_id,
            stage=stage,
            agent_name="ReviewerAgent",
            input_refs=[f"mode={mode.value}"],
            output_ref=output_ref,
            llm_resp=llm_resp,
            decision=f"status={result.status.value}",
            reasons=[i.rule_id for i in result.issues] or ["pass"],
            warnings=[i.problem for i in result.issues] or None,
        )

        return result

    def _get_mode_prompt(self, mode: ReviewerMode) -> str:
        if mode == ReviewerMode.EVIDENCE:
            return self._evidence_mode_prompt()
        elif mode == ReviewerMode.CONTENT:
            return self._content_mode_prompt()
        elif mode == ReviewerMode.LAYOUT:
            return self._layout_mode_prompt()
        return ""

    def _evidence_mode_prompt(self) -> str:
        return """## Evidence 审核清单
检查以下问题，发现时输出 issue（rule_id 用 EVIDENCE_XXX）：
- EVIDENCE_001：claim 是否被来源直接支持？来源是否可靠及时？
- EVIDENCE_002：是否把宣传/营销文案当成了实际功能效果？
- EVIDENCE_003：是否缺少限制条件或反例？（如只说优点不说适用边界）
- EVIDENCE_004：趋势类 claim 是否有至少2个独立来源？（COPY_004/EVIDENCE_007）
- EVIDENCE_005：证据不足的结论是否已写入 uncertainties 而非作为核心 Claim？
- EVIDENCE_006：provenance 是否不含 creator？（博主观点应走 editorial_thesis）

## LLM 知识模式（关键规则，避免无限重试）
当所有 source 的 snapshot_ref 为 "llm_knowledge" 时，说明当前处于无网络环境，
ResearchAgent 已用模型知识兜底生成证据。此时**禁止**再以"来源未经实时验证"为由
输出 revise/route_to=researching（重新研究仍会得到 LLM 知识，会形成无限循环）。

LLM 知识模式下的判定规则：
- 若 claims 结构完整（有 claim_id/claim/epistemic_type/content_role/provenance）、
  枚举值合法、每个 claim 的 source_ids 都有对应 evidence_snippet、
  uncertainties 中已注明"基于模型知识生成，未经实时验证" → status=pass，
  并在 issues 中加一条 severity=minor 的 warning（rule_id=EVIDENCE_007,
  location="evidence_pack", problem="证据基于LLM知识生成，未经实时验证",
  suggested_action="发布前人工核对关键事实"）。
- 仅当出现结构性错误（枚举值错误、snippet 缺失、provenance 含 creator、
  严重事实编造）时，才输出 revise 或 failed。

## 判定优先级
1. 严重事实编造/安全风险 → status=failed, severity=blocking。
2. LLM 知识模式且结构完整 → status=pass（附 EVIDENCE_007 minor warning）。
3. 非LLM知识模式下证据不足 → status=revise, route_to=researching。
4. 证据充分可靠 → status=pass（无 issue）。"""

    def _content_mode_prompt(self) -> str:
        return """## Content 审核清单
检查以下问题，发现时输出 issue（rule_id 用 CONTENT_XXX/COPY_XXX/STYLE_XXX/VOICE_XXX）：
- CONTENT_001：是否出现证据包外的新事实？
- CONTENT_003：external_claim/mixed block 是否都有 claim_refs？
- CONTENT_004：标题是否夸张？是否含未经证据支持的绝对化结论？
- CONTENT_005：技术术语首次出现是否已用人话解释？
- CONTENT_006：是否存在可识别的核心判断（editorial_thesis）？
- CONTENT_007：正文和卡片是否大段重复？（逐字>30字或重合率>70%触发检查）
- COPY_001：产品拆解类是否说明了限制/边界/待验证点？
- COPY_002：是否包含产品视角判断？
- COPY_003：趋势类是否说明了时间边界？
- STYLE_009：标签是否5-8个？
- STYLE_010：正文是否400-700字？
- STYLE_011：标题是否12-22个中文显示宽度？
- VOICE_001：是否堆专业黑话？
- VOICE_002：判断是否说明了依据和不确定性？

如果内容符合规则 → status=pass。
如果需修改文案 → status=revise, route_to=drafting。
如果严重事实错误/安全风险 → status=failed, severity=blocking。"""

    def _layout_mode_prompt(self) -> str:
        return """## Layout 审核清单
检查以下问题，发现时输出 issue（rule_id 用 VISUAL_XXX/STYLE_XXX）：
- VISUAL_001：画布是否1080×1440，安全区72px？
- VISUAL_004：信息层级是否清晰？DOM 是否可能溢出/遮挡？
- VISUAL_006：每张卡片是否有非纯文本的信息组织元素？
- VISUAL_007：素材是否通过 asset_manifest 管理？是否只引用 available_assets 中的 asset_id？
- STYLE_005：卡片数量是否5-8张？
- STYLE_012：是否页面过于拥挤？字体是否可读（正文最小32px）？
- 卡片间是否信息重复？

如果布局合理 → status=pass。
如果需调整布局 → status=revise, route_to=visual_planning。
如果严重视觉错误 → status=failed, severity=blocking。"""

    def _build_context(
        self,
        mode: ReviewerMode,
        evidence_pack: Optional[EvidencePack],
        card_outline: Optional[CardOutline],
        draft: Optional[Draft],
        layout_spec: Optional[LayoutSpec],
    ) -> str:
        parts = []
        if evidence_pack is not None:
            parts.append(f"## EvidencePack\n{evidence_pack.model_dump_json(indent=2)}")
        if card_outline is not None:
            parts.append(f"## CardOutline\n{card_outline.model_dump_json(indent=2)}")
        if draft is not None:
            parts.append(f"## Draft\n{draft.model_dump_json(indent=2)}")
        if layout_spec is not None:
            parts.append(f"## LayoutSpec\n{layout_spec.model_dump_json(indent=2)}")
        return "\n\n".join(parts)
