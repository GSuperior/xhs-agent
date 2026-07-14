"""xhs_agent 数据契约 Schema（Pydantic v2）。

按模块导出所有枚举、类型与模型，供 Controller / Agents / Validators 共享。
"""

from .common import (
    CONTENT_TYPE_LABELS,
    REVIEWER_ROUTE_WHITELIST,
    AssetSource,
    AssetType,
    ContentRole,
    ContentType,
    EpistemicType,
    IssueType,
    LifecycleType,
    Provenance,
    ReviewStatus,
    ReviewerMode,
    RunState,
    Severity,
    StatementType,
)
from .content import (
    AngleHypothesis,
    Block,
    CardOutline,
    CardSpec,
    Cover,
    CoverSubtitle,
    DiscoveryCandidate,
    Draft,
    EditorialThesis,
    PostTitleCandidate,
    SelectedTopic,
    TopicBrief,
)
from .evidence import (
    Claim,
    EvidencePack,
    EvidenceSnippet,
    Source,
)
from .review import (
    HumanReviewState,
    ReviewIssue,
    ReviewerResult,
)
from .visual import (
    AssetManifest,
    AssetManifestEntry,
    AvailableAsset,
    AvailableAssets,
    LayoutSpec,
    LayoutSpecItem,
)

__all__ = [
    # common
    "CONTENT_TYPE_LABELS",
    "REVIEWER_ROUTE_WHITELIST",
    "AssetSource",
    "AssetType",
    "ContentRole",
    "ContentType",
    "EpistemicType",
    "IssueType",
    "LifecycleType",
    "Provenance",
    "ReviewStatus",
    "ReviewerMode",
    "RunState",
    "Severity",
    "StatementType",
    # content
    "AngleHypothesis",
    "Block",
    "CardOutline",
    "CardSpec",
    "Cover",
    "CoverSubtitle",
    "DiscoveryCandidate",
    "Draft",
    "EditorialThesis",
    "PostTitleCandidate",
    "SelectedTopic",
    "TopicBrief",
    # evidence
    "Claim",
    "EvidencePack",
    "EvidenceSnippet",
    "Source",
    # review
    "HumanReviewState",
    "ReviewIssue",
    "ReviewerResult",
    # visual
    "AssetManifest",
    "AssetManifestEntry",
    "AvailableAsset",
    "AvailableAssets",
    "LayoutSpec",
    "LayoutSpecItem",
]
