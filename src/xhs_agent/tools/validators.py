"""三个确定性 Validator：Schema Validator + Reference Validator + Render Validator。

均为纯结构/引用校验，不做语义判断（语义判断由 Reviewer Agent 负责）。
"""

import re
from typing import List

from pydantic import ValidationError

from ..schemas.content import CardOutline, Draft
from ..schemas.evidence import EvidencePack
from ..schemas.visual import LayoutSpec


class ValidationResult:
    """校验结果。passed=True 表示通过；errors 为错误说明列表。"""

    def __init__(self, passed: bool, errors: List[str] = None):
        self.passed = passed
        self.errors = errors or []

    def __bool__(self) -> bool:
        return self.passed

    def add(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False


class SchemaValidator:
    """Pydantic 模型结构校验。"""

    @staticmethod
    def validate_evidence(data: dict) -> ValidationResult:
        try:
            EvidencePack.model_validate(data)
            return ValidationResult(passed=True)
        except ValidationError as e:
            return ValidationResult(passed=False, errors=[str(e)])

    @staticmethod
    def validate_card_outline(data: dict) -> ValidationResult:
        try:
            CardOutline.model_validate(data)
            return ValidationResult(passed=True)
        except ValidationError as e:
            return ValidationResult(passed=False, errors=[str(e)])

    @staticmethod
    def validate_draft(data: dict) -> ValidationResult:
        try:
            Draft.model_validate(data)
            return ValidationResult(passed=True)
        except ValidationError as e:
            return ValidationResult(passed=False, errors=[str(e)])

    @staticmethod
    def validate_layout_spec(data: dict) -> ValidationResult:
        try:
            LayoutSpec.model_validate(data)
            return ValidationResult(passed=True)
        except ValidationError as e:
            return ValidationResult(passed=False, errors=[str(e)])

    @staticmethod
    def validate_draft_enhanced(
        draft: Draft, card_outline: CardOutline = None
    ) -> ValidationResult:
        """Draft 软规则校验：检查可程序化的内容质量约束（STYLE_009/010 等）。

        覆盖以下约束（不阻断流程，返回详细错误列表供 Reviewer 重点复核）：
          - body_text 长度 400-700 字（STYLE_010）
          - tags 数量 5-8 个（STYLE_009）
          - post_title_candidates 数量 ≥ 3（设计要求3个不同方向候选）
          - card_1 的 visual_type 必须为 "cover"（需传入 card_outline）
        """
        result = ValidationResult(passed=True)

        # body_text 长度 400-700 字（STYLE_010）
        body_len = len(draft.body_text) if draft.body_text else 0
        if body_len < 400 or body_len > 700:
            result.add(
                f"body_text 长度 {body_len} 字，超出 400-700 字范围（STYLE_010）"
            )

        # tags 数量 5-8 个（STYLE_009）
        tags_count = len(draft.tags)
        if tags_count < 5 or tags_count > 8:
            result.add(
                f"tags 数量 {tags_count} 个，超出 5-8 个范围（STYLE_009）"
            )

        # post_title_candidates 数量 ≥ 3（设计要求3个不同方向候选）
        titles_count = len(draft.post_title_candidates)
        if titles_count < 3:
            result.add(
                f"post_title_candidates 数量 {titles_count} 个，少于设计要求的 3 个"
                f"（需覆盖疑问钩子型/判断承诺型/盘点型三个方向）"
            )

        # card_1 的 visual_type 必须为 "cover"（需传入 card_outline）
        if card_outline is not None:
            card_1 = next(
                (c for c in card_outline.cards if c.card_id == "card_1"), None
            )
            if card_1 is None:
                result.add("card_outline 中缺少 card_id='card_1' 的封面卡片")
            elif card_1.visual_type != "cover":
                result.add(
                    f"card_1 的 visual_type 为 {card_1.visual_type!r}，必须为 'cover'"
                )

        return result


class ReferenceValidator:
    """引用链完整性校验，覆盖 12 类引用点。不做语义判断。

    校验内容：
      EvidencePack:
        1. claims[].source_ids 指向存在的 source
        2. claims[].context_source_ids 指向存在的 source
        3. claims[].evidence_snippets[].source_id 指向存在的 source
        4. source_ids 中每个 source 必须有对应 snippet
        5. source 必须有 url/publisher/source_type，accessed_at 必填
      CardOutline:
        6. editorial_thesis.supporting_claim_refs 指向存在的 claim
        7. cards[].claim_refs 指向存在的 claim
        8. cards[].thesis_ref 只能为 "editorial_thesis" 或 null；
           非空时 outline 中必须存在 editorial_thesis
      Draft:
        9.  blocks[].claim_refs 指向存在的 claim
        10. blocks[].supporting_claim_refs 指向存在的 claim
        11. post_title_candidates[].claim_refs 指向存在的 claim
        12. post_title_candidates[].supporting_claim_refs 指向存在的 claim
        13. cover.subtitle.claim_refs 指向存在的 claim
        14. cover.subtitle.supporting_claim_refs 指向存在的 claim
    """

    # ------------------------------------------------------------------
    # EvidencePack
    # ------------------------------------------------------------------
    @staticmethod
    def validate_evidence_pack(evidence: EvidencePack) -> ValidationResult:
        result = ValidationResult(passed=True)
        source_ids = {s.source_id for s in evidence.sources}

        for claim in evidence.claims:
            # 1. claims[].source_ids 指向存在的 source
            for sid in claim.source_ids:
                if sid not in source_ids:
                    result.add(
                        f"Claim {claim.claim_id} 的 source_ids 引用了不存在的 source: {sid}"
                    )
            # 2. claims[].context_source_ids 指向存在的 source
            for sid in claim.context_source_ids:
                if sid not in source_ids:
                    result.add(
                        f"Claim {claim.claim_id} 的 context_source_ids 引用了不存在的 source: {sid}"
                    )
            # 3. claims[].evidence_snippets[].source_id 指向存在的 source
            for snippet in claim.evidence_snippets:
                if snippet.source_id not in source_ids:
                    result.add(
                        f"Claim {claim.claim_id} 的 evidence_snippet 引用了不存在的 source: {snippet.source_id}"
                    )
            # 4. source_ids 中每个 source 必须有对应 snippet
            snippet_source_ids = {s.source_id for s in claim.evidence_snippets}
            for sid in claim.source_ids:
                if sid not in snippet_source_ids:
                    result.add(
                        f"Claim {claim.claim_id} 的 source_id {sid} 缺少对应的 evidence_snippet"
                    )

        # 5. source 必须有 url/publisher/source_type，accessed_at 必填
        #    （Pydantic 模型已强制 accessed_at 必填，这里补做非空校验）
        for src in evidence.sources:
            if not src.url:
                result.add(f"Source {src.source_id} 缺少 url")
            if not src.publisher:
                result.add(f"Source {src.source_id} 缺少 publisher")
            if not src.source_type:
                result.add(f"Source {src.source_id} 缺少 source_type")
            if not src.accessed_at:
                result.add(f"Source {src.source_id} 缺少 accessed_at")

        return result

    # ------------------------------------------------------------------
    # CardOutline
    # ------------------------------------------------------------------
    @staticmethod
    def validate_card_outline(
        outline: CardOutline, evidence: EvidencePack
    ) -> ValidationResult:
        result = ValidationResult(passed=True)
        claim_ids = {c.claim_id for c in evidence.claims}

        # 6. editorial_thesis.supporting_claim_refs 指向存在的 claim
        thesis = outline.editorial_thesis
        if thesis is not None:
            for ref in thesis.supporting_claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"editorial_thesis.supporting_claim_refs 引用了不存在的 claim: {ref}"
                    )

        for card in outline.cards:
            # 7. cards[].claim_refs 指向存在的 claim
            for ref in card.claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"Card {card.card_id} 的 claim_refs 引用了不存在的 claim: {ref}"
                    )
            # 8. cards[].thesis_ref 只能为 "editorial_thesis" 或 null；
            #     非空时 outline 中必须存在 editorial_thesis
            if card.thesis_ref is not None:
                if card.thesis_ref != "editorial_thesis":
                    result.add(
                        f"Card {card.card_id} 的 thesis_ref 只能为 'editorial_thesis' 或 null，"
                        f"得到: {card.thesis_ref!r}"
                    )
                elif outline.editorial_thesis is None:
                    result.add(
                        f"Card {card.card_id} 的 thesis_ref='editorial_thesis'，"
                        f"但 outline 中不存在 editorial_thesis"
                    )

        return result

    # ------------------------------------------------------------------
    # Draft
    # ------------------------------------------------------------------
    @staticmethod
    def validate_draft(draft: Draft, evidence: EvidencePack) -> ValidationResult:
        result = ValidationResult(passed=True)
        claim_ids = {c.claim_id for c in evidence.claims}

        for block in draft.blocks:
            # 9. blocks[].claim_refs 指向存在的 claim
            for ref in block.claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"Block {block.block_id} 的 claim_refs 引用了不存在的 claim: {ref}"
                    )
            # 10. blocks[].supporting_claim_refs 指向存在的 claim
            for ref in block.supporting_claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"Block {block.block_id} 的 supporting_claim_refs 引用了不存在的 claim: {ref}"
                    )

        for i, title in enumerate(draft.post_title_candidates):
            # 11. post_title_candidates[].claim_refs 指向存在的 claim
            for ref in title.claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"post_title_candidates[{i}] 的 claim_refs 引用了不存在的 claim: {ref}"
                    )
            # 12. post_title_candidates[].supporting_claim_refs 指向存在的 claim
            for ref in title.supporting_claim_refs:
                if ref not in claim_ids:
                    result.add(
                        f"post_title_candidates[{i}] 的 supporting_claim_refs 引用了不存在的 claim: {ref}"
                    )

        # 13. cover.subtitle.claim_refs 指向存在的 claim
        subtitle = draft.cover.subtitle
        for ref in subtitle.claim_refs:
            if ref not in claim_ids:
                result.add(
                    f"cover.subtitle.claim_refs 引用了不存在的 claim: {ref}"
                )
        # 14. cover.subtitle.supporting_claim_refs 指向存在的 claim
        for ref in subtitle.supporting_claim_refs:
            if ref not in claim_ids:
                result.add(
                    f"cover.subtitle.supporting_claim_refs 引用了不存在的 claim: {ref}"
                )

        return result


class RenderValidator:
    """渲染产物校验。

    Phase 1A 简化：检查 HTML 非空、包含 card div、字号符合 design token。
    完整版会检查尺寸(1080x1440)、安全区(72px)、溢出、缺失元素。
    """

    @staticmethod
    def validate_html(html: str, design_token: dict) -> ValidationResult:
        result = ValidationResult(passed=True)

        if not html or not html.strip():
            result.add("HTML 为空")
            return result

        # 检查包含 card div（class 或 id 含 "card"）
        if not re.search(r'class\s*=\s*"[^"]*card', html, re.IGNORECASE) and \
           not re.search(r'id\s*=\s*"[^"]*card', html, re.IGNORECASE):
            result.add("HTML 中未找到 card div（class/id 含 'card'）")

        # 检查画布尺寸引用（Phase1A：HTML 中应出现 1080 / 1440）
        canvas = design_token.get("canvas", {}) if design_token else {}
        expected_w = str(canvas.get("width", 1080))
        expected_h = str(canvas.get("height", 1440))
        if expected_w not in html or expected_h not in html:
            result.add(
                f"HTML 中未找到画布尺寸 {expected_w}x{expected_h} 的引用"
            )

        # 检查字号符合 token：提取 style 中的 font-size 值，校验是否在
        # design_token["font_scale"] 允许集合内（不匹配记为错误）
        font_scale = design_token.get("font_scale", {}) if design_token else {}
        allowed_sizes = {str(v) for v in font_scale.values()} if font_scale else set()
        if allowed_sizes:
            # 匹配 font-size: 76px / font-size:76px 等
            for match in re.finditer(r"font-size\s*:\s*(\d+)px", html, re.IGNORECASE):
                size = match.group(1)
                if size not in allowed_sizes:
                    result.add(
                        f"HTML 中 font-size:{size}px 不在 design_token.font_scale 允许值内: "
                        f"{sorted(allowed_sizes)}"
                    )

        return result
