from enum import Enum
from typing import Optional, Literal


class ContentType(str, Enum):
    PRODUCT_BREAKDOWN = "product_breakdown"
    TREND_ANALYSIS = "trend_analysis"
    KNOWLEDGE_EXPLAINER = "knowledge_explainer"
    HANDS_ON_TUTORIAL = "hands_on_tutorial"
    COMPARISON_REVIEW = "comparison_review"
    INDUSTRY_OBSERVATION = "industry_observation"


CONTENT_TYPE_LABELS = {
    ContentType.PRODUCT_BREAKDOWN: "产品拆解",
    ContentType.TREND_ANALYSIS: "趋势解读",
    ContentType.KNOWLEDGE_EXPLAINER: "知识科普",
    ContentType.HANDS_ON_TUTORIAL: "实战教程",
    ContentType.COMPARISON_REVIEW: "对比评测",
    ContentType.INDUSTRY_OBSERVATION: "产业观察",
}


class ContentRole(str, Enum):
    CORE = "core"
    BACKGROUND = "background"
    COMPARISON = "comparison"
    LIMITATION = "limitation"
    CASE = "case"
    TREND = "trend"


class EpistemicType(str, Enum):
    FACTUAL = "factual"
    INTERPRETIVE = "interpretive"
    PROJECTIVE = "projective"
    EXPERIENTIAL = "experiential"


class Provenance(str, Enum):
    OFFICIAL = "official"
    MEDIA = "media"
    COMMUNITY = "community"
    USER = "user"


class StatementType(str, Enum):
    EXTERNAL_CLAIM = "external_claim"
    CREATOR_OPINION = "creator_opinion"
    MIXED = "mixed"


class LifecycleType(str, Enum):
    BREAKING = "breaking"
    TRENDING = "trending"
    EVERGREEN = "evergreen"
    SERIES = "series"


class RunState(str, Enum):
    INIT = "INIT"
    DISCOVERING = "DISCOVERING"
    TOPIC_ANGLE_CONFIRMATION = "TOPIC_ANGLE_CONFIRMATION"
    RESEARCHING = "RESEARCHING"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    OUTLINING = "OUTLINING"
    OUTLINE_CONFIRMATION = "OUTLINE_CONFIRMATION"
    DRAFTING = "DRAFTING"
    CONTENT_REVIEW = "CONTENT_REVIEW"
    VISUAL_PLANNING = "VISUAL_PLANNING"
    LAYOUT_REVIEW = "LAYOUT_REVIEW"
    RENDERING = "RENDERING"
    RENDER_VALIDATION = "RENDER_VALIDATION"
    FINAL_CONFIRMATION = "FINAL_CONFIRMATION"
    COMPLETED = "COMPLETED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    FAILED = "FAILED"


class ReviewerMode(str, Enum):
    EVIDENCE = "evidence"
    CONTENT = "content"
    LAYOUT = "layout"


class ReviewStatus(str, Enum):
    PASS = "pass"
    REVISE = "revise"
    BLOCKED = "blocked"
    FAILED = "failed"


class IssueType(str, Enum):
    EVIDENCE = "evidence"
    OUTLINE = "outline"
    COPY = "copy"
    LAYOUT = "layout"
    RENDER = "render"
    SAFETY = "safety"


class Severity(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"
    BLOCKING = "blocking"


class AssetType(str, Enum):
    LOGO = "logo"
    SCREENSHOT = "screenshot"
    ICON = "icon"
    ILLUSTRATION = "illustration"


class AssetSource(str, Enum):
    USER_PROVIDED = "user_provided"
    LIBRARY = "library"
    GENERATED = "generated"


# Reviewer route_to 白名单
REVIEWER_ROUTE_WHITELIST = [
    "researching", "outlining", "drafting",
    "visual_planning", "rendering", "human_review", "failed"
]
