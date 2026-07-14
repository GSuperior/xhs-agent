from typing import Any, List, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

from .common import ContentRole, EpistemicType, Provenance


class EvidenceSnippet(BaseModel):
    """Claim 的子字段：原文短摘录 + 来源ID + 在原文中的位置。"""
    source_id: str
    snippet: str
    location: str


class Source(BaseModel):
    """证据来源。保存来源快照（snapshot_ref + content_hash）供 Evidence Reviewer 核对原文。"""
    source_id: str
    publisher: str
    url: str
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    accessed_at: str  # 必填
    version_or_commit: Optional[str] = None
    source_type: Literal["primary", "media", "user", "community"]
    snapshot_ref: str
    content_hash: str


class Claim(BaseModel):
    """外部 Claim（provenance 不含 creator）。博主观点走 editorial_thesis。"""
    claim_id: str
    claim: str
    epistemic_type: EpistemicType
    content_role: ContentRole
    provenance: Provenance
    source_ids: List[str]
    context_source_ids: List[str] = []
    evidence_snippets: List[EvidenceSnippet] = []
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str
    time_scope: str
    applicability: str

    @model_validator(mode="after")
    def validate_claim_snippets(self) -> "Claim":
        """source_ids 中每个 source 都必须在 evidence_snippets 中有对应 source_id 的 snippet。"""
        snippet_source_ids = {s.source_id for s in self.evidence_snippets}
        missing = [sid for sid in self.source_ids if sid not in snippet_source_ids]
        if missing:
            raise ValueError(
                f"Claim {self.claim_id} 的 source_ids 中存在无对应 evidence_snippet 的来源: {missing}"
            )
        return self


class EvidencePack(BaseModel):
    """证据包。仅包含外部 Claim，provenance 不含 creator。uncertainties 记录证据不足的情况。"""
    topic: str
    event_time: Optional[str] = None
    claims: List[Claim]
    sources: List[Source]
    uncertainties: List[str] = []
    content_opportunities: List[str] = []

    @field_validator("content_opportunities", "uncertainties", mode="before")
    @classmethod
    def coerce_to_str_list(cls, v: Any) -> Any:
        """LLM 可能返回 dict/对象列表而非字符串列表，统一转为字符串。"""
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                # 尝试提取常见字段，否则 JSON 序列化
                for key in ("text", "description", "opportunity", "content", "value"):
                    if key in item and isinstance(item[key], str):
                        result.append(item[key])
                        break
                else:
                    import json
                    result.append(json.dumps(item, ensure_ascii=False))
            else:
                result.append(str(item))
        return result
