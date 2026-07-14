from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

from .common import ContentType, LifecycleType, StatementType


# ---------------------------------------------------------------------------
# 选题发现与策划
# ---------------------------------------------------------------------------

class DiscoveryCandidate(BaseModel):
    """选题发现阶段产出的轻量候选。"""
    topic_id: str
    title: str
    source_urls: List[str] = []
    published_at: Optional[str] = None
    what_happened: str
    target_audience: str
    product_angle: str
    why_now: str
    shareability: float
    evidence_quality: float
    technical_difficulty: float
    lifecycle: LifecycleType
    valid_until: str
    content_type: ContentType
    content_type_label: str
    topic_subtype: Optional[str] = None


class SelectedTopic(BaseModel):
    """用户从候选中选中的话题。结构与候选对齐，作为后续 TopicBrief 的输入。"""
    topic_id: str
    title: str
    source_urls: List[str] = []
    published_at: Optional[str] = None
    what_happened: str
    target_audience: str
    product_angle: str
    why_now: str
    lifecycle: LifecycleType
    valid_until: str
    content_type: ContentType
    content_type_label: str
    topic_subtype: Optional[str] = None


class AngleHypothesis(BaseModel):
    """研究前的待验证角度，放在 topic_brief 中。此时无 Claim ID。"""
    statement: str
    questions_to_verify: List[str] = []


class TopicBrief(BaseModel):
    """选题详细简报，含 angle_hypothesis（研究前）。"""
    topic: str
    target_reader: str
    reader_problem: str
    one_sentence_value: str
    core_angle: str
    content_type: ContentType
    content_type_label: str
    topic_subtype: Optional[str] = None
    hook: str
    expected_takeaway: List[str] = []
    differentiation: str
    avoid: List[str] = []
    research_questions: List[str] = []
    angle_hypothesis: AngleHypothesis


# ---------------------------------------------------------------------------
# 内容规划（卡片大纲）
# ---------------------------------------------------------------------------

class EditorialThesis(BaseModel):
    """研究后的博主核心判断，放在 card_outline 中。
    通过 supporting_claim_refs 关联外部 Claim，用 certainty 标记判断置信度。
    """
    statement: str
    supporting_claim_refs: List[str] = []
    certainty: Literal["high", "medium", "low"]


class CardSpec(BaseModel):
    """卡片内容意图（purpose/key_message/key_points），不写具体文案。"""
    card_id: str
    purpose: str
    key_message: str
    key_points: List[str] = []
    claim_refs: List[str] = []
    thesis_ref: Optional[Literal["editorial_thesis"]] = None
    visual_type: str
    max_chars: int

    @field_validator("thesis_ref")
    @classmethod
    def validate_thesis_ref(cls, v: Optional[str]) -> Optional[str]:
        """thesis_ref 只能为 "editorial_thesis" 或 None。"""
        if v is not None and v != "editorial_thesis":
            raise ValueError(
                f"thesis_ref 只能为 'editorial_thesis' 或 None，得到: {v!r}"
            )
        return v


class CardOutline(BaseModel):
    """卡片大纲。card_1 固定为封面，card_outline 和 draft 的 cover 都引用 card_id='card_1'。"""
    editorial_thesis: EditorialThesis
    cards: List[CardSpec]


# ---------------------------------------------------------------------------
# 文案（Draft）
# ---------------------------------------------------------------------------

class Block(BaseModel):
    """文案块。surface=body 时 card_id 必须为 None；surface=card 时 card_id 必填。
    statement_type=external_claim 或 mixed 时 claim_refs 不能为空。
    """
    block_id: str
    surface: Literal["body", "card"]
    card_id: Optional[str] = None
    text: str
    statement_type: StatementType
    claim_refs: List[str] = []
    supporting_claim_refs: List[str] = []

    @model_validator(mode="after")
    def validate_block_constraints(self) -> "Block":
        # surface 与 card_id 联动
        if self.surface == "body" and self.card_id is not None:
            raise ValueError(
                f"Block {self.block_id} surface=body 时 card_id 必须为 None，"
                f"得到: {self.card_id!r}"
            )
        if self.surface == "card" and self.card_id is None:
            raise ValueError(
                f"Block {self.block_id} surface=card 时 card_id 必填"
            )
        # statement_type 与 claim_refs 联动
        if self.statement_type in (StatementType.EXTERNAL_CLAIM, StatementType.MIXED) \
                and not self.claim_refs:
            raise ValueError(
                f"Block {self.block_id} statement_type={self.statement_type.value} "
                f"时 claim_refs 不能为空"
            )
        return self


class PostTitleCandidate(BaseModel):
    """标题候选。包含外部事实时必须有 claim_refs。"""
    text: str
    statement_type: StatementType
    claim_refs: List[str] = []
    supporting_claim_refs: List[str] = []


class CoverSubtitle(BaseModel):
    """封面副标题。包含外部事实时必须有 claim_refs。"""
    text: str
    statement_type: StatementType
    claim_refs: List[str] = []
    supporting_claim_refs: List[str] = []


class Cover(BaseModel):
    """封面。card_id 固定为 'card_1'。"""
    card_id: Literal["card_1"] = "card_1"
    series_label: str
    main_title: str
    subtitle: CoverSubtitle


class Draft(BaseModel):
    """文案产出：post_title_candidates + cover + blocks + body_text + tags。"""
    post_title_candidates: List[PostTitleCandidate]
    cover: Cover
    blocks: List[Block]
    body_text: str
    tags: List[str] = []
