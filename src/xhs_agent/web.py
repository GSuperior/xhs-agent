"""xhs_agent Web 端 — FastAPI 接入层。

把 CLI 的 XHSAgent 14 态主链路改造为 HTTP API：
- 长耗时操作（daily / select / confirm / revise）在后台线程执行，
  立刻返回 run_id，前端通过轮询 /api/runs/{run_id}/state 看进度。
- 不调用 input()：用 WebAgent 子类复用 XHSAgent 的所有内部方法，
  把交互式确认节点拆成独立的 API 入口。

启动方式：
    python -m xhs_agent.web          # 推荐
    python src/xhs_agent/web.py      # 也支持
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 路径 / 工作目录修正
# 保证无论从哪里启动，都能找到 xhs_agent 包，且 ./runs 解析到 /workspace/runs。
# Vercel 环境：文件系统只读，需把 config/ 和 runs/ 复制到 /tmp 可写目录。
# ---------------------------------------------------------------------------
import shutil as _shutil

_ROOT = Path(__file__).resolve().parents[2]  # /workspace
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))

if _IS_VERCEL:
    # Vercel Serverless 文件系统只读，只有 /tmp 可写。
    # 冷启动时把 config/ 和 runs/ 复制到 /tmp，后续 Controller 写入落到可写目录。
    _WORKSPACE = Path("/tmp/xhs_ws")
    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    for _sub in ("config", "runs"):
        _src_dir = _ROOT / _sub
        _dst_dir = _WORKSPACE / _sub
        if _src_dir.exists():
            try:
                _shutil.copytree(_src_dir, _dst_dir, dirs_exist_ok=True)
            except Exception:
                pass
    os.chdir(_WORKSPACE)
    RUNS_DIR = _WORKSPACE / "runs"
else:
    # 本地：Controller / ArtifactStore / DecisionLogger 用相对路径 ./runs，
    # 必须把 cwd 切到项目根，否则会写到错误目录。
    try:
        os.chdir(_ROOT)
    except Exception:
        pass
    RUNS_DIR = _ROOT / "runs"

# 复用现有实现（不修改 cli.py / agents / schemas / tools）
try:
    from .cli import XHSAgent
    from .controller import Controller
    from .schemas.common import RunState, ReviewerMode, ReviewStatus
    from .schemas.content import (
        AngleHypothesis,
        CardOutline,
        Draft,
        SelectedTopic,
        TopicBrief,
    )
    from .schemas.evidence import EvidencePack
    from .schemas.visual import AvailableAssets
    from .agents import DiscoveryCandidates
except ImportError:  # 以脚本方式运行：python src/xhs_agent/web.py
    from xhs_agent.cli import XHSAgent
    from xhs_agent.controller import Controller
    from xhs_agent.schemas.common import RunState, ReviewerMode, ReviewStatus
    from xhs_agent.schemas.content import (
        AngleHypothesis,
        CardOutline,
        Draft,
        SelectedTopic,
        TopicBrief,
    )
    from xhs_agent.schemas.evidence import EvidencePack
    from xhs_agent.schemas.visual import AvailableAssets
    from xhs_agent.agents import DiscoveryCandidates

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# ===========================================================================
# 运行态元数据（web_status / web_error），持久化到 state.json
# ===========================================================================

_WEB_STATUS: Dict[str, Dict[str, Any]] = {}


def _state_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "state.json"


def _read_state_json(run_id: str) -> Optional[dict]:
    p = _state_path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_state_json(run_id: str, data: dict) -> None:
    p = _state_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_status(run_id: str, status: str, error: Optional[str] = None) -> None:
    """更新 web 运行态并合并写入 state.json。"""
    _WEB_STATUS[run_id] = {"status": status, "error": error}
    data = _read_state_json(run_id) or {}
    data["web_status"] = status
    data["web_error"] = error
    _write_state_json(run_id, data)


def _clear_status(run_id: str) -> None:
    _WEB_STATUS.pop(run_id, None)
    data = _read_state_json(run_id)
    if data:
        data["web_status"] = "idle"
        data["web_error"] = None
        _write_state_json(run_id, data)


def _is_running(run_id: str) -> bool:
    data = _read_state_json(run_id)
    return bool(data and data.get("web_status") == "running")


# ===========================================================================
# WebAgent —— 复用 XHSAgent 内部方法，剥离 input() 交互
# ===========================================================================

class WebAgent(XHSAgent):
    """Web 化的 Agent：复用 XHSAgent 全部内部方法，但不在内部调用 input()。

    把确认节点拆成独立入口：
      - daily          → DISCOVERING → TOPIC_ANGLE_CONFIRMATION（停）
      - select         → RESEARCHING → ... → OUTLINE_CONFIRMATION（停）
      - confirm(大纲)  → DRAFTING → ... → FINAL_CONFIRMATION（停）
      - confirm(终稿)  → COMPLETED
      - revise(大纲)  → 重新调 planning_agent（停在 OUTLINE_CONFIRMATION）
      - revise(终稿)  → 重新调 writing_agent + visual_agent + renderer（停在 FINAL_CONFIRMATION）
    """

    # ---- 状态持久化（覆盖父类，附带写入 web_status）----
    def _save_state(self, run_id: str):
        state_info = self.controller.get_state_info()
        meta = _WEB_STATUS.get(run_id, {})
        state_info["web_status"] = meta.get("status", "idle")
        state_info["web_error"] = meta.get("error")
        state_path = RUNS_DIR / run_id / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- daily：选题发现，停在 TOPIC_ANGLE_CONFIRMATION ----
    def run_daily(self, run_id: str) -> None:
        self._restore_controller(run_id)
        # DISCOVERING
        if self.controller.state != RunState.DISCOVERING:
            self.controller.transition(RunState.DISCOVERING)
        self._save_state(run_id)
        candidates_result = self.topic_agent.execute(run_id, topic="")
        # 进入 TOPIC_ANGLE_CONFIRMATION
        self.controller.transition(RunState.TOPIC_ANGLE_CONFIRMATION)
        self._save_state(run_id)

    # ---- select 之后的：RESEARCHING → ... → OUTLINE_CONFIRMATION ----
    def run_research_to_outline(self, run_id: str) -> None:
        self._restore_controller(run_id)
        topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
        selected = self._load_artifact_model(run_id, "selected_topic", SelectedTopic)
        if topic_brief is None or selected is None:
            raise RuntimeError("缺少 topic_brief / selected_topic，无法继续。")
        source_urls = selected.source_urls or []
        self._web_research_to_outline(run_id, topic_brief, source_urls)

    def _web_research_to_outline(
        self, run_id: str, topic_brief: TopicBrief, source_urls: list
    ) -> None:
        # === RESEARCHING ===
        self.controller.transition(RunState.RESEARCHING)
        self._save_state(run_id)
        evidence_pack = self.research_agent.execute(
            run_id, topic_brief, source_urls=source_urls
        )

        # === EVIDENCE_REVIEW ===
        self.controller.transition(RunState.EVIDENCE_REVIEW)
        self._save_state(run_id)
        review_result = self._run_evidence_review(run_id, evidence_pack)
        if review_result is None:
            raise RuntimeError("证据审核返回空结果。")
        if review_result.status == ReviewStatus.FAILED:
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            raise RuntimeError("证据审核 FAILED，流程终止。")
        if review_result.status in (ReviewStatus.REVISE, ReviewStatus.BLOCKED):
            if review_result.status == ReviewStatus.REVISE and self.controller.can_research():
                self.controller.research_count += 1
                self._save_state(run_id)
                evidence_pack = self.research_agent.execute(
                    run_id, topic_brief, source_urls=source_urls
                )
                review_result = self._run_evidence_review(run_id, evidence_pack)
                if review_result is None or review_result.status == ReviewStatus.FAILED:
                    self.controller.transition(RunState.FAILED)
                    self._save_state(run_id)
                    raise RuntimeError("证据审核(重试)未通过。")
            else:
                self.controller.transition(RunState.HUMAN_REVIEW)
                self._save_state(run_id)
                raise RuntimeError("证据审核需人工介入。")

        # === OUTLINING ===
        self.controller.transition(RunState.OUTLINING)
        self._save_state(run_id)
        card_outline = self.planning_agent.execute(run_id, topic_brief, evidence_pack)

        # === OUTLINE_CONFIRMATION（停，等用户确认）===
        self.controller.transition(RunState.OUTLINE_CONFIRMATION)
        self._save_state(run_id)

    # ---- confirm(大纲)：DRAFTING → ... → FINAL_CONFIRMATION ----
    def run_draft_to_final(self, run_id: str) -> None:
        self._restore_controller(run_id)
        topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
        evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
        card_outline = self._load_artifact_model(run_id, "card_outline", CardOutline)
        if not all([topic_brief, evidence_pack, card_outline]):
            raise RuntimeError("缺少 topic_brief / evidence_pack / card_outline。")
        self._web_draft_to_final(run_id, topic_brief, evidence_pack, card_outline)

    def _web_draft_to_final(
        self, run_id: str, topic_brief: TopicBrief,
        evidence_pack: EvidencePack, card_outline: CardOutline,
    ) -> None:
        # === DRAFTING ===
        self.controller.transition(RunState.DRAFTING)
        self._save_state(run_id)
        draft = self.writing_agent.execute(
            run_id, card_outline, evidence_pack, topic_brief
        )

        # === CONTENT_REVIEW ===
        self.controller.transition(RunState.CONTENT_REVIEW)
        self._save_state(run_id)
        review_result = self._run_content_review(
            run_id, card_outline, evidence_pack, draft
        )
        if review_result is None:
            raise RuntimeError("内容审核返回空结果。")
        if review_result.status == ReviewStatus.FAILED:
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            raise RuntimeError("内容审核 FAILED，流程终止。")
        if review_result.status in (ReviewStatus.REVISE, ReviewStatus.BLOCKED):
            if review_result.status == ReviewStatus.REVISE and self.controller.can_revise_copy():
                self.controller.copy_revise_count += 1
                self._save_state(run_id)
                draft = self.writing_agent.execute(
                    run_id, card_outline, evidence_pack, topic_brief
                )
                review_result = self._run_content_review(
                    run_id, card_outline, evidence_pack, draft
                )
                if review_result is None or review_result.status == ReviewStatus.FAILED:
                    self.controller.transition(RunState.FAILED)
                    self._save_state(run_id)
                    raise RuntimeError("内容审核(重试)未通过。")
            else:
                self.controller.transition(RunState.HUMAN_REVIEW)
                self._save_state(run_id)
                raise RuntimeError("内容审核需人工介入。")

        # === VISUAL_PLANNING ===
        self.controller.transition(RunState.VISUAL_PLANNING)
        self._save_state(run_id)
        available_assets = AvailableAssets(available_assets=[])
        visual_plan = self.visual_agent.execute(
            run_id, card_outline, draft,
            available_assets, self.config.design_token,
        )

        # === LAYOUT_REVIEW ===
        self.controller.transition(RunState.LAYOUT_REVIEW)
        self._save_state(run_id)
        review_result = self._run_layout_review(
            run_id, visual_plan.layout_spec, draft
        )
        if review_result is None:
            raise RuntimeError("布局审核返回空结果。")
        if review_result.status == ReviewStatus.FAILED:
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            raise RuntimeError("布局审核 FAILED，流程终止。")
        if review_result.status in (ReviewStatus.REVISE, ReviewStatus.BLOCKED):
            if review_result.status == ReviewStatus.REVISE and self.controller.can_revise_layout():
                self.controller.layout_revise_count += 1
                self._save_state(run_id)
                visual_plan = self.visual_agent.execute(
                    run_id, card_outline, draft,
                    available_assets, self.config.design_token,
                )
                review_result = self._run_layout_review(
                    run_id, visual_plan.layout_spec, draft
                )
                if review_result is None or review_result.status == ReviewStatus.FAILED:
                    self.controller.transition(RunState.FAILED)
                    self._save_state(run_id)
                    raise RuntimeError("布局审核(重试)未通过。")
            else:
                self.controller.transition(RunState.HUMAN_REVIEW)
                self._save_state(run_id)
                raise RuntimeError("布局审核需人工介入。")

        # === RENDERING ===
        self.controller.transition(RunState.RENDERING)
        self._save_state(run_id)
        html_content = self.renderer.render_html(
            visual_plan.layout_spec, draft,
            visual_plan.asset_manifest, self.config.design_token,
        )
        html_path = RUNS_DIR / run_id / "output" / "note.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_content, encoding="utf-8")

        # === RENDER_VALIDATION ===
        self.controller.transition(RunState.RENDER_VALIDATION)
        self._save_state(run_id)
        render_result = self.render_validator.validate_html(
            html_content, self.config.design_token
        )
        # 渲染校验警告不阻断（与 CLI 一致）

        # === FINAL_CONFIRMATION（停，等用户确认终稿）===
        self.controller.transition(RunState.FINAL_CONFIRMATION)
        self._save_state(run_id)

    # ---- confirm(终稿)：标记 COMPLETED ----
    def run_complete(self, run_id: str) -> None:
        self._restore_controller(run_id)
        self.controller.transition(RunState.COMPLETED)
        self._save_state(run_id)

    # ---- revise(大纲)：重新调 planning_agent ----
    def run_revise_outline(self, run_id: str, instruction: str) -> None:
        self._restore_controller(run_id)
        topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
        evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
        if not all([topic_brief, evidence_pack]):
            raise RuntimeError("缺少 topic_brief / evidence_pack。")
        if not self.controller.can_revise_outline():
            raise RuntimeError("大纲修改预算耗尽。")
        self.controller.outline_revise_count += 1
        # instruction 通过日志决策理由记录（planning_agent 不接受 instruction 参数）
        self.controller.logger.log(
            run_id, "OUTLINE_REVISE", "WebAgent",
            input_refs=["topic_brief", "evidence_pack"],
            output_ref=f"runs/{run_id}/artifacts/card_outline/",
            model="user",
            duration_ms=0,
            token_usage={},
            decision=f"用户修改大纲指令: {instruction}",
            decision_reasons=[instruction],
            warnings=[],
            status="success",
        )
        card_outline = self.planning_agent.execute(run_id, topic_brief, evidence_pack)
        # 停在 OUTLINE_CONFIRMATION
        self.controller.transition(RunState.OUTLINE_CONFIRMATION)
        self._save_state(run_id)

    # ---- revise(终稿)：重新撰写文案 + 视觉规划 + 渲染 ----
    def run_revise_final(self, run_id: str, instruction: str) -> None:
        self._restore_controller(run_id)
        topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
        evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
        card_outline = self._load_artifact_model(run_id, "card_outline", CardOutline)
        if not all([topic_brief, evidence_pack, card_outline]):
            raise RuntimeError("缺少必要的 artifact。")
        if not self.controller.can_revise_copy():
            raise RuntimeError("文案修改预算耗尽。")
        self.controller.copy_revise_count += 1
        self.controller.logger.log(
            run_id, "FINAL_REVISE", "WebAgent",
            input_refs=["card_outline", "evidence_pack", "topic_brief"],
            output_ref=f"runs/{run_id}/artifacts/draft/",
            model="user",
            duration_ms=0,
            token_usage={},
            decision=f"用户修改终稿指令: {instruction}",
            decision_reasons=[instruction],
            warnings=[],
            status="success",
        )
        draft = self.writing_agent.execute(
            run_id, card_outline, evidence_pack, topic_brief
        )
        available_assets = AvailableAssets(available_assets=[])
        visual_plan = self.visual_agent.execute(
            run_id, card_outline, draft,
            available_assets, self.config.design_token,
        )
        html_content = self.renderer.render_html(
            visual_plan.layout_spec, draft,
            visual_plan.asset_manifest, self.config.design_token,
        )
        html_path = RUNS_DIR / run_id / "output" / "note.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_content, encoding="utf-8")
        # 停在 FINAL_CONFIRMATION
        self.controller.transition(RunState.FINAL_CONFIRMATION)
        self._save_state(run_id)


# ===========================================================================
# 后台任务调度
# ===========================================================================

def _launch(run_id: str, fn, *args) -> None:
    def _worker():
        try:
            _set_status(run_id, "running")
            fn(*args)
            _clear_status(run_id)
        except Exception as e:  # noqa: BLE001
            # 标记失败
            agent = WebAgent()
            try:
                agent._restore_controller(run_id)
                agent.controller.transition(RunState.FAILED)
                agent._save_state(run_id)
            except Exception:
                pass
            err = f"{type(e).__name__}: {e}"
            _set_status(run_id, "error", err)
            traceback.print_exc()

    t = threading.Thread(target=_worker, daemon=True, name=f"xhs-{run_id}")
    t.start()


# ===========================================================================
# FastAPI 应用
# ===========================================================================

app = FastAPI(title="XHS Agent Web", version="1.0.0")

_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---- 请求体模型 ----
class SelectBody(BaseModel):
    topic_id: str


class ReviseBody(BaseModel):
    instruction: str


# ---- 工具函数 ----
def _require_run(run_id: str) -> Path:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} 不存在。")
    return run_dir


def _load_artifact_raw(run_id: str, name: str) -> Optional[dict]:
    art_dir = RUNS_DIR / run_id / "artifacts" / name
    if not art_dir.exists():
        return None
    versions = sorted(art_dir.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    if not versions:
        return None
    return json.loads(versions[-1].read_text(encoding="utf-8"))


# ===========================================================================
# 路由：前端
# ===========================================================================

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = _STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=500)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ===========================================================================
# 路由：runs 列表 / 状态 / 产物
# ===========================================================================

STATE_ORDER = [
    "INIT", "DISCOVERING", "TOPIC_ANGLE_CONFIRMATION", "RESEARCHING",
    "EVIDENCE_REVIEW", "OUTLINING", "OUTLINE_CONFIRMATION", "DRAFTING",
    "CONTENT_REVIEW", "VISUAL_PLANNING", "LAYOUT_REVIEW", "RENDERING",
    "RENDER_VALIDATION", "FINAL_CONFIRMATION", "COMPLETED",
]

STATE_LABELS = {
    "INIT": "初始化",
    "DISCOVERING": "选题发现",
    "TOPIC_ANGLE_CONFIRMATION": "选题确认",
    "RESEARCHING": "研究取证",
    "EVIDENCE_REVIEW": "证据审核",
    "OUTLINING": "内容规划",
    "OUTLINE_CONFIRMATION": "大纲确认",
    "DRAFTING": "文案撰写",
    "CONTENT_REVIEW": "内容审核",
    "VISUAL_PLANNING": "视觉规划",
    "LAYOUT_REVIEW": "布局审核",
    "RENDERING": "渲染",
    "RENDER_VALIDATION": "渲染校验",
    "FINAL_CONFIRMATION": "终稿确认",
    "COMPLETED": "完成",
    "HUMAN_REVIEW": "人工审核",
    "FAILED": "失败",
}

# 进度条用的 14 个态（不含 INIT）
PROGRESS_STATES = STATE_ORDER[1:]


@app.get("/api/runs")
def list_runs() -> JSONResponse:
    if not RUNS_DIR.exists():
        return JSONResponse({"runs": [], "state_order": PROGRESS_STATES,
                            "state_labels": STATE_LABELS})
    runs = []
    for sub in RUNS_DIR.iterdir():
        if not sub.is_dir():
            continue
        state_data = _read_state_json(sub.name) or {}
        # 标题：优先 selected_topic，其次 discovery_candidates 第一条
        title = None
        sel = _load_artifact_raw(sub.name, "selected_topic")
        if sel:
            title = sel.get("title")
        if not title:
            cand = _load_artifact_raw(sub.name, "discovery_candidates")
            if cand and cand.get("candidates"):
                title = cand["candidates"][0].get("title")
        runs.append({
            "run_id": sub.name,
            "state": state_data.get("state", "UNKNOWN"),
            "web_status": state_data.get("web_status", "idle"),
            "web_error": state_data.get("web_error"),
            "title": title,
            "outline_revise_count": state_data.get("outline_revise_count", 0),
            "copy_revise_count": state_data.get("copy_revise_count", 0),
        })
    runs.sort(key=lambda r: r["run_id"], reverse=True)
    return JSONResponse({
        "runs": runs,
        "state_order": PROGRESS_STATES,
        "state_labels": STATE_LABELS,
    })


@app.get("/api/runs/{run_id}/state")
def get_state(run_id: str) -> JSONResponse:
    _require_run(run_id)
    data = _read_state_json(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="state.json 不存在。")
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/candidates")
def get_candidates(run_id: str) -> JSONResponse:
    _require_run(run_id)
    data = _load_artifact_raw(run_id, "discovery_candidates")
    if data is None:
        raise HTTPException(status_code=404, detail="discovery_candidates 不存在。")
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/outline")
def get_outline(run_id: str) -> JSONResponse:
    _require_run(run_id)
    data = _load_artifact_raw(run_id, "card_outline")
    if data is None:
        raise HTTPException(status_code=404, detail="card_outline 不存在。")
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/draft")
def get_draft(run_id: str) -> JSONResponse:
    _require_run(run_id)
    data = _load_artifact_raw(run_id, "draft")
    if data is None:
        raise HTTPException(status_code=404, detail="draft 不存在。")
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/html", response_class=HTMLResponse)
def get_html(run_id: str) -> HTMLResponse:
    _require_run(run_id)
    html_path = RUNS_DIR / run_id / "output" / "note.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="note.html 尚未生成。")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/log")
def get_log(run_id: str) -> JSONResponse:
    _require_run(run_id)
    log_path = RUNS_DIR / run_id / "run_log.jsonl"
    if not log_path.exists():
        return JSONResponse({"entries": []})
    entries = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            entries.append({"raw": line})
    return JSONResponse({"entries": entries})


@app.get("/api/runs/{run_id}/artifacts")
def list_artifacts(run_id: str) -> JSONResponse:
    _require_run(run_id)
    art_dir = RUNS_DIR / run_id / "artifacts"
    out = []
    if art_dir.exists():
        for sub in sorted(art_dir.iterdir()):
            if not sub.is_dir():
                continue
            versions = sorted(sub.glob("v*.json"), key=lambda p: int(p.stem[1:]))
            out.append({
                "name": sub.name,
                "versions": [v.name for v in versions],
                "latest": versions[-1].name if versions else None,
            })
    return JSONResponse({"artifacts": out})


# ===========================================================================
# 路由：动作（长耗时，后台执行）
# ===========================================================================

@app.post("/api/daily")
def api_daily() -> JSONResponse:
    # 同步创建 run（快），返回 run_id；选题发现放后台
    agent = WebAgent()
    run_id = agent.controller.start("daily_hot_discovery")
    agent._save_state(run_id)
    _launch(run_id, _bg_daily, run_id)
    return JSONResponse({"run_id": run_id, "status": "running"})


def _bg_daily(run_id: str) -> None:
    agent = WebAgent()
    agent.run_daily(run_id)


@app.post("/api/runs/{run_id}/select")
def api_select(run_id: str, body: SelectBody) -> JSONResponse:
    _require_run(run_id)
    if _is_running(run_id):
        raise HTTPException(status_code=409, detail="该 run 正在执行任务，请等待完成。")
    state = _read_state_json(run_id) or {}
    current = state.get("state", "INIT")
    if current != "TOPIC_ANGLE_CONFIRMATION":
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {current} 不允许选择话题，需在 TOPIC_ANGLE_CONFIRMATION。",
        )
    # 同步做话题选择（快）
    agent = WebAgent()
    agent._restore_controller(run_id)
    data = agent.store.load_artifact(run_id, "discovery_candidates")
    if data is None:
        raise HTTPException(status_code=400, detail="未找到 discovery_candidates。")
    candidates_result = DiscoveryCandidates.model_validate(data)
    selected_candidate = None
    for c in candidates_result.candidates:
        if c.topic_id == body.topic_id:
            selected_candidate = c
            break
    if selected_candidate is None:
        raise HTTPException(
            status_code=400,
            detail=f"未找到 topic_id={body.topic_id}。",
        )
    selected = SelectedTopic(
        topic_id=selected_candidate.topic_id,
        title=selected_candidate.title,
        source_urls=selected_candidate.source_urls,
        published_at=selected_candidate.published_at,
        what_happened=selected_candidate.what_happened,
        target_audience=selected_candidate.target_audience,
        product_angle=selected_candidate.product_angle,
        why_now=selected_candidate.why_now,
        lifecycle=selected_candidate.lifecycle,
        valid_until=selected_candidate.valid_until,
        content_type=selected_candidate.content_type,
        content_type_label=selected_candidate.content_type_label,
        topic_subtype=selected_candidate.topic_subtype,
    )
    agent._save_artifact(run_id, "selected_topic", selected)
    topic_brief = agent._build_topic_brief(selected)
    agent._save_artifact(run_id, "topic_brief", topic_brief)
    # 进入 RESEARCHING（标记进行中），后台跑研究→大纲
    agent.controller.transition(RunState.RESEARCHING)
    agent._save_state(run_id)
    _launch(run_id, _bg_research_to_outline, run_id)
    return JSONResponse({"run_id": run_id, "status": "running",
                         "selected_topic": selected.title})


def _bg_research_to_outline(run_id: str) -> None:
    agent = WebAgent()
    agent.run_research_to_outline(run_id)


@app.post("/api/runs/{run_id}/confirm")
def api_confirm(run_id: str) -> JSONResponse:
    _require_run(run_id)
    if _is_running(run_id):
        raise HTTPException(status_code=409, detail="该 run 正在执行任务，请等待完成。")
    state = _read_state_json(run_id) or {}
    current = state.get("state", "INIT")

    if current == "OUTLINE_CONFIRMATION":
        _launch(run_id, _bg_draft_to_final, run_id)
        return JSONResponse({"run_id": run_id, "status": "running",
                             "action": "draft_to_final"})

    if current == "FINAL_CONFIRMATION":
        # 同步标记完成（快）
        agent = WebAgent()
        agent.run_complete(run_id)
        return JSONResponse({"run_id": run_id, "status": "completed",
                             "action": "complete"})

    raise HTTPException(
        status_code=400,
        detail=f"当前状态 {current} 不支持 confirm。支持: OUTLINE_CONFIRMATION / FINAL_CONFIRMATION。",
    )


def _bg_draft_to_final(run_id: str) -> None:
    agent = WebAgent()
    agent.run_draft_to_final(run_id)


@app.post("/api/runs/{run_id}/revise")
def api_revise(run_id: str, body: ReviseBody) -> JSONResponse:
    _require_run(run_id)
    if _is_running(run_id):
        raise HTTPException(status_code=409, detail="该 run 正在执行任务，请等待完成。")
    state = _read_state_json(run_id) or {}
    current = state.get("state", "INIT")
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction 不能为空。")

    if current == "OUTLINE_CONFIRMATION":
        _launch(run_id, _bg_revise_outline, run_id, instruction)
        return JSONResponse({"run_id": run_id, "status": "running",
                             "action": "revise_outline"})

    if current in ("FINAL_CONFIRMATION", "COMPLETED"):
        # COMPLETED 也允许重新生成文案（重开到 FINAL_CONFIRMATION）
        _launch(run_id, _bg_revise_final, run_id, instruction)
        return JSONResponse({"run_id": run_id, "status": "running",
                             "action": "revise_final"})

    raise HTTPException(
        status_code=400,
        detail=f"当前状态 {current} 不支持 revise。支持: OUTLINE_CONFIRMATION / FINAL_CONFIRMATION / COMPLETED。",
    )


def _bg_revise_outline(run_id: str, instruction: str) -> None:
    agent = WebAgent()
    agent.run_revise_outline(run_id, instruction)


def _bg_revise_final(run_id: str, instruction: str) -> None:
    agent = WebAgent()
    agent.run_revise_final(run_id, instruction)


# ===========================================================================
# 入口
# ===========================================================================

def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """启动 uvicorn 服务。"""
    import uvicorn
    uvicorn.run(
        "xhs_agent.web:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
