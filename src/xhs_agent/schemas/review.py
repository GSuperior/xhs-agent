from typing import Dict, List, Optional

from pydantic import BaseModel, model_validator

from .common import (
    REVIEWER_ROUTE_WHITELIST,
    IssueType,
    ReviewStatus,
    Severity,
)


class ReviewIssue(BaseModel):
    """单条审核问题。每个 issue 必须带 rule_id（与 style_rules 规则ID一致）。"""
    rule_id: str
    location: str
    problem: str
    severity: Severity
    suggested_action: str = ""


class ReviewerResult(BaseModel):
    """Reviewer 三模式统一结构化结果。
    - pass: issue_type=null, route_to=null
    - revise: route_to 必须在 REVIEWER_ROUTE_WHITELIST 中
    - failed: severity 必须为 blocking
    """
    status: ReviewStatus
    issue_type: Optional[IssueType] = None
    route_to: Optional[str] = None
    issues: List[ReviewIssue] = []
    severity: Severity = Severity.NONE

    @model_validator(mode="after")
    def validate_reviewer_result(self) -> "ReviewerResult":
        # pass 时 issue_type 和 route_to 必须为 None
        if self.status == ReviewStatus.PASS:
            if self.issue_type is not None or self.route_to is not None:
                raise ValueError(
                    "status=pass 时 issue_type 和 route_to 必须为 None，"
                    f"得到 issue_type={self.issue_type!r}, route_to={self.route_to!r}"
                )
        # revise 时 route_to 必须在白名单中
        if self.status == ReviewStatus.REVISE:
            if self.route_to is None or self.route_to not in REVIEWER_ROUTE_WHITELIST:
                raise ValueError(
                    f"status=revise 时 route_to 必须在白名单 {REVIEWER_ROUTE_WHITELIST} 中，"
                    f"得到: {self.route_to!r}"
                )
        # failed 时 severity 必须为 blocking
        if self.status == ReviewStatus.FAILED:
            if self.severity != Severity.BLOCKING:
                raise ValueError(
                    f"status=failed 时 severity 必须为 blocking，得到: {self.severity!r}"
                )
        return self


class HumanReviewState(BaseModel):
    """HUMAN_REVIEW 状态数据。action_routes 动态生成，映射用户动作到下一状态。"""
    blocking_reason: str
    required_action: str
    action_routes: Dict[str, str]
