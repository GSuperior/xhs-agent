"""HTML 渲染工具，用 Jinja2 生成 HTML + Playwright 截图 PNG。

- Jinja2 开启自动转义（防 XSS）。
- Playwright 未安装时优雅降级：只生成 HTML 不截图。
- 模板路径：{templates_dir}/{template_name}/card.html.j2
- 模板缺失时使用内置 fallback 模板。
"""

from pathlib import Path
from typing import Any, Optional

from jinja2 import (
    Environment,
    FileSystemLoader,
    ChoiceLoader,
    DictLoader,
    select_autoescape,
)

from ..schemas.visual import AssetManifest, LayoutSpec
from ..schemas.content import Draft


# 模板根目录：/workspace/src/xhs_agent/templates
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# 内容类型 → 中文标签映射（用于 caption 动态渲染）
from ..schemas.common import CONTENT_TYPE_LABELS
_CONTENT_TYPE_LABELS = {k.value: v for k, v in CONTENT_TYPE_LABELS.items()}

# 内置 fallback 卡片模板（当 templates/{name}/card.html.j2 不存在时使用）。
# 仅卡片片段，不含 DOCTYPE/html/head/body —— 外壳由 page 模板统一组装。
_FALLBACK_CARD_TEMPLATE = """\
<div class="card card-{{ card_id }}" style="
    width: {{ design_token.canvas.width }}px;
    min-height: {{ design_token.canvas.height }}px;
    padding: {{ design_token.canvas.safe_area }}px;
    box-sizing: border-box;
    background: {{ design_token.content_theme.background }};
    color: {{ design_token.content_theme.foreground }};
    font-size: {{ design_token.font_scale.card_body }}px;
    line-height: {{ design_token.line_height.body }};
">
{% if card_heading %}
    <h2 class="card-heading" style="font-size: {{ design_token.font_scale.card_heading }}px; line-height: {{ design_token.line_height.heading }};">{{ card_heading }}</h2>
{% endif %}
{% if key_message %}
    <p class="key-message">{{ key_message }}</p>
{% endif %}
{% for block in blocks %}
    <div class="block block-{{ block.surface }}">{{ block.text }}</div>
{% endfor %}
</div>"""

# page 级模板：1 个外层 HTML 文档 + N 个卡片片段。
# 所有 <style> 集中在 <head>，覆盖 cover/timeline/trend/comparison/case/conclusion
# 六种视觉类型，font-size 取值严格对齐 design_token.font_scale。
_FALLBACK_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={{ design_token.canvas.width }}, height={{ design_token.canvas.height }}">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: {{ design_token.canvas.width }}px;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased;
  background: {{ design_token.cover_theme.background }};
}
.page { width: {{ design_token.canvas.width }}px; }
.card {
  width: {{ design_token.canvas.width }}px;
  height: {{ design_token.canvas.height }}px;
  position: relative;
  overflow: hidden;
  margin: 0 auto;
}

/* ===== 封面 cover ===== */
.cover {
  background: {{ design_token.cover_theme.background }};
  color: {{ design_token.cover_theme.foreground }};
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: {{ design_token.canvas.safe_area }}px;
}
.cover .series-label {
  font-size: {{ design_token.font_scale.cover_subtitle }}px;
  color: #999;
  letter-spacing: 3px;
  margin-bottom: 32px;
  font-weight: 500;
}
.cover .main-title {
  font-size: {{ design_token.font_scale.cover_main }}px;
  font-weight: 800;
  color: {{ design_token.cover_theme.foreground }};
  text-align: center;
  line-height: {{ design_token.line_height.heading }};
  max-width: 800px;
  word-break: break-word;
}
.cover .subtitle {
  font-size: {{ design_token.font_scale.cover_subtitle }}px;
  color: #666;
  margin-top: 32px;
  text-align: center;
  line-height: {{ design_token.line_height.body }};
  max-width: 700px;
}
.cover .badge {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translateX(-50%);
  background: {{ design_token.cover_theme.foreground }};
  color: {{ design_token.cover_theme.background }};
  border-radius: 999px;
  padding: 12px 32px;
  font-size: {{ design_token.font_scale.badge }}px;
  white-space: nowrap;
  font-weight: 500;
}
.cover .corner {
  position: absolute;
  width: 100px;
  height: 100px;
  border: 3px solid {{ design_token.cover_theme.foreground }};
}
.cover .corner-tl { top: 48px; left: 48px; border-right: none; border-bottom: none; }
.cover .corner-tr { top: 48px; right: 48px; border-left: none; border-bottom: none; }
.cover .corner-bl { bottom: 48px; left: 48px; border-right: none; border-top: none; }
.cover .corner-br { bottom: 48px; right: 48px; border-left: none; border-top: none; }
.cover .timeline-arrow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}
.cover .arrow-line { width: 80px; height: 3px; background: {{ design_token.cover_theme.foreground }}; }
.cover .arrow-head {
  width: 0; height: 0;
  border-left: 16px solid {{ design_token.cover_theme.foreground }};
  border-top: 10px solid transparent;
  border-bottom: 10px solid transparent;
}
.cover .arrow-dot {
  width: 12px; height: 12px; border-radius: 50%;
  background: {{ design_token.content_theme.accent }};
}

/* ===== 内容卡片通用 ===== */
.content-card {
  background: {{ design_token.content_theme.background }};
  padding: {{ design_token.canvas.safe_area }}px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.content-card .torn-top {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 12px;
  background-image: linear-gradient(135deg, transparent 50%, {{ design_token.content_theme.background }} 50%),
                      linear-gradient(225deg, transparent 50%, {{ design_token.content_theme.background }} 50%);
  background-size: 24px 12px;
  background-repeat: repeat-x;
}
.content-card .heading {
  font-size: {{ design_token.font_scale.card_heading }}px;
  font-weight: 700;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.heading }};
  margin-bottom: 4px;
}
.content-card .body {
  font-size: {{ design_token.font_scale.card_body }}px;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.body }};
}
.content-card .caption {
  font-size: {{ design_token.font_scale.caption }}px;
  color: #999;
  margin-top: auto;
  padding-top: 16px;
  text-align: center;
}
.content-card .white-card {
  background: #fff;
  border-radius: 20px;
  padding: 36px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}
.content-card .highlight-card {
  background: {{ design_token.content_theme.accent }};
  color: #fff;
  border-radius: 20px;
  padding: 36px;
  box-shadow: 0 4px 24px rgba(255,107,138,0.2);
}

/* ===== timeline 时间线 ===== */
.timeline-card .timeline-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: relative;
  padding-left: 56px;
  flex: 1;
}
.timeline-card .timeline-line {
  position: absolute;
  left: 16px; top: 20px; bottom: 20px;
  width: 4px;
  background: {{ design_token.content_theme.accent }};
  opacity: 0.3;
  border-radius: 2px;
}
.timeline-card .timeline-item {
  position: relative;
  background: #fff;
  border-radius: 16px;
  padding: 22px 28px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.timeline-card .timeline-item::before {
  content: '';
  position: absolute;
  left: -46px; top: 26px;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: {{ design_token.content_theme.accent }};
  border: 4px solid #fff;
  box-shadow: 0 0 0 2px {{ design_token.content_theme.accent }};
}
.timeline-card .timeline-item-header {
  font-size: {{ design_token.font_scale.card_body }}px;
  font-weight: 700;
  color: {{ design_token.content_theme.accent }};
  margin-bottom: 6px;
}
.timeline-card .timeline-item-text {
  font-size: {{ design_token.font_scale.card_body }}px;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.body }};
}

/* ===== trend 趋势 ===== */
.trend-card .trend-headline {
  font-size: {{ design_token.font_scale.card_heading }}px;
  font-weight: 800;
  text-align: center;
  color: {{ design_token.content_theme.accent }};
  padding: 28px 20px;
  line-height: {{ design_token.line_height.heading }};
  background: #fff;
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}
.trend-card .trend-arrow {
  font-size: {{ design_token.font_scale.card_heading }}px;
  text-align: center;
  color: {{ design_token.content_theme.accent }};
  font-weight: 800;
  line-height: 1;
}
.trend-card .trend-signals {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  flex: 1;
}
.trend-card .trend-signal {
  background: #fff;
  border-radius: 16px;
  padding: 22px 14px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.trend-card .trend-signal-num {
  width: 48px; height: 48px;
  border-radius: 50%;
  background: {{ design_token.content_theme.accent }};
  color: #fff;
  font-size: {{ design_token.font_scale.badge }}px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}
.trend-card .trend-signal-text {
  font-size: {{ design_token.font_scale.caption }}px;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.body }};
}

/* ===== comparison 对比 ===== */
.comparison-card .comp-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  flex: 1;
}
.comparison-card .comp-col {
  background: #fff;
  border-radius: 16px;
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.comparison-card .comp-col-header {
  font-size: {{ design_token.font_scale.card_body }}px;
  font-weight: 700;
  color: {{ design_token.content_theme.accent }};
  text-align: center;
  padding-bottom: 10px;
  border-bottom: 2px solid {{ design_token.content_theme.background }};
}
.comparison-card .comp-footer {
  background: {{ design_token.content_theme.accent }};
  color: #fff;
  border-radius: 16px;
  padding: 20px 28px;
  font-size: {{ design_token.font_scale.caption }}px;
  line-height: {{ design_token.line_height.body }};
}

/* ===== case 案例 ===== */
.case-card .case-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  flex: 1;
}
.case-card .case-col {
  background: #fff;
  border-radius: 16px;
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.case-card .case-col-title {
  font-size: {{ design_token.font_scale.card_body }}px;
  font-weight: 700;
  color: {{ design_token.content_theme.accent }};
  text-align: center;
  padding-bottom: 10px;
  border-bottom: 2px solid {{ design_token.content_theme.background }};
}
.case-card .case-col-item {
  font-size: {{ design_token.font_scale.caption }}px;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.body }};
  padding-left: 24px;
  position: relative;
}
.case-card .case-col-item::before {
  content: '•';
  position: absolute;
  left: 8px;
  color: {{ design_token.content_theme.accent }};
  font-weight: 700;
}

/* ===== conclusion 结论 ===== */
.conclusion-card .concl-center {
  text-align: center;
  padding: 32px 28px;
  background: #fff;
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}
.conclusion-card .concl-message {
  font-size: {{ design_token.font_scale.card_body }}px;
  font-weight: 700;
  color: {{ design_token.content_theme.accent }};
  line-height: {{ design_token.line_height.body }};
}
.conclusion-card .concl-points {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  flex: 1;
}
.conclusion-card .concl-point {
  background: #fff;
  border-radius: 16px;
  padding: 24px 18px;
  text-align: center;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.conclusion-card .concl-point-num {
  width: 48px; height: 48px;
  border-radius: 50%;
  background: {{ design_token.content_theme.accent }};
  color: #fff;
  font-size: {{ design_token.font_scale.badge }}px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
}
.conclusion-card .concl-point-text {
  font-size: {{ design_token.font_scale.caption }}px;
  color: {{ design_token.content_theme.foreground }};
  line-height: {{ design_token.line_height.body }};
}
.conclusion-card .concl-opportunity {
  background: {{ design_token.content_theme.accent }};
  color: #fff;
  border-radius: 16px;
  padding: 20px 28px;
  font-size: {{ design_token.font_scale.caption }}px;
  line-height: {{ design_token.line_height.body }};
  text-align: center;
}
</style>
</head>
<body>
<div class="page">
{% for card_html in card_htmls %}
{{ card_html | safe }}
{% endfor %}
</div>
</body>
</html>"""


def _to_dict(obj: Any) -> Any:
    """将 Pydantic 模型转为 dict，dict/list 递归处理。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


class Renderer:
    """HTML/PNG 渲染器。"""

    def __init__(self, templates_dir: str = None):
        self.templates_dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        # Jinja2 环境：FileSystemLoader + DictLoader(fallback)，开启自动转义
        self.env = Environment(
            loader=ChoiceLoader(
                [
                    FileSystemLoader(str(self.templates_dir)),
                    DictLoader(
                        {
                            "_fallback_card.html.j2": _FALLBACK_CARD_TEMPLATE,
                            "_fallback_page.html.j2": _FALLBACK_PAGE_TEMPLATE,
                        }
                    ),
                ]
            ),
            autoescape=select_autoescape(["html", "xml", "j2"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _get_card_template(self, template_name: str):
        """优先加载 {template_name}/card.html.j2，缺失时用 fallback。"""
        tpl_path = f"{template_name}/card.html.j2"
        try:
            return self.env.get_template(tpl_path)
        except Exception:
            return self.env.get_template("_fallback_card.html.j2")

    @staticmethod
    def _parse_card_content(
        blocks: list, key_message: str, template_type: str
    ) -> dict:
        """把单张卡片的文案块解析为结构化内容，供模板按视觉类型渲染。

        遍历所有 blocks，把每个 block 的 text 作为独立条目。
        返回 dict: {header, items, footer, raw_text, block_items}
        - header: 冒号前的标题部分（如 "厂商策略分化"）
        - items: 拆分后的条目列表（用于时间线/网格/信号格）
        - footer: 对比卡的总结行
        - raw_text: 所有 block 文案合并
        - block_items: 每个 block 对应一个 {header, text} 条目，保留完整内容
        """
        # 收集所有 block 的文本（不再只取 blocks[0]）
        all_texts = []
        for b in blocks:
            t = b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
            if t:
                all_texts.append(t)

        text = "\n".join(all_texts) if all_texts else (key_message or "")

        result = {
            "header": "",
            "items": [],
            "footer": "",
            "raw_text": text,
            "block_items": [],
        }
        if not text:
            return result

        # 构建 block_items：每个 block 独立条目，保留完整内容
        for b in blocks:
            t = b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
            if not t:
                continue
            item = {"header": "", "text": t}
            if "：" in t:
                h, rest = t.split("：", 1)
                item["header"] = h.strip()
                item["text"] = rest.strip()
            result["block_items"].append(item)

        # 兼容旧的 items/footer 逻辑（从合并文本推导）
        rest = text
        if "：" in text:
            header, rest = text.split("：", 1)
            result["header"] = header.strip()

        if template_type == "comparison":
            # 每个 block 作为独立对比项
            result["items"] = [it["text"] for it in result["block_items"]]
            # 最后一个 block 作为 footer（总结行）
            if len(result["block_items"]) > 1:
                result["footer"] = result["block_items"][-1]["text"]
                result["items"] = [it["text"] for it in result["block_items"][:-1]]
            else:
                result["footer"] = ""
        elif template_type in ("trend", "conclusion"):
            # block_items 作为要点
            result["items"] = [it["text"] for it in result["block_items"]][:5]
            if not result["header"] and result["block_items"]:
                result["header"] = result["block_items"][0].get("header") or result["block_items"][0]["text"][:20]
        else:
            # timeline / case：每个 block 作为独立条目
            result["items"] = [it["text"] for it in result["block_items"]]
        return result

    # ------------------------------------------------------------------
    # 单卡渲染
    # ------------------------------------------------------------------
    def render_card_html(
        self,
        card_data: dict,
        template_name: str,
        design_token: dict,
        layout_card: dict = None,
        cover: dict = None,
        content_type_label: str = "",
    ) -> str:
        """渲染单张卡片 HTML 片段（不含 DOCTYPE/html/head/body）。

        card_data 可包含：card_id, card_heading, key_message, blocks, assets。
        layout_card 为 layout_spec 中对应卡片的规格（template/hierarchy/emphasis/icon_keys）。
        cover 为 draft.cover dict，供封面渲染 series_label 等动态字段。
        content_type_label 用于 caption 动态渲染（如 "产品拆解"/"趋势解读"）。
        """
        tpl = self._get_card_template(template_name)
        layout_card = layout_card or {}
        cover = cover or {}
        template_type = layout_card.get("template", "")
        blocks = [_to_dict(b) for b in card_data.get("blocks", [])]
        key_message = card_data.get("key_message", "")
        card_content = self._parse_card_content(
            blocks, key_message, template_type
        )
        ctx = {
            "card_id": card_data.get("card_id", ""),
            "card_heading": card_data.get("card_heading")
            or card_data.get("key_message", ""),
            "key_message": key_message,
            "blocks": blocks,
            "assets": [_to_dict(a) for a in card_data.get("assets", [])],
            "design_token": design_token,
            "layout_card": layout_card,
            "cover": cover,
            "content_type_label": content_type_label,
            "card_content": card_content,
            "account_name": design_token.get("account_name", "AI产品经理GSuperior") if isinstance(design_token, dict) else "AI产品经理GSuperior",
        }
        return tpl.render(**ctx)

    # ------------------------------------------------------------------
    # 整页渲染
    # ------------------------------------------------------------------
    def render_html(
        self,
        layout_spec: LayoutSpec,
        draft: Draft,
        asset_manifest: AssetManifest,
        design_token: dict,
        template_name: str = None,
    ) -> str:
        """根据 layout_spec + draft + asset_manifest 渲染整页 HTML。

        组装方式：1 个外层 HTML 文档（page 模板）+ N 个卡片片段。
        template_name 缺省时取 layout_spec.template。
        """
        if template_name is None:
            template_name = layout_spec.template

        layout_dict = _to_dict(layout_spec)
        draft_dict = _to_dict(draft)
        assets_dict = _to_dict(asset_manifest)

        # 内容类型标签（用于 caption 动态渲染）
        content_type_label = _CONTENT_TYPE_LABELS.get(
            layout_dict.get("template", ""), layout_dict.get("template", "")
        )

        # 按 card_id 索引 layout_spec 中的卡片规格（template/hierarchy/emphasis/icon_keys）
        layout_card_map: dict[str, dict] = {}
        for card in layout_dict.get("cards", []):
            cid = card.get("card_id", "")
            layout_card_map[cid] = card

        # 按 card_id 索引 card blocks
        card_blocks: dict[str, list] = {}
        body_blocks: list = []
        for block in draft_dict.get("blocks", []):
            if block.get("surface") == "card":
                cid = block.get("card_id", "")
                card_blocks.setdefault(cid, []).append(block)
            else:
                body_blocks.append(block)

        # 按 used_in_cards 索引 assets
        card_assets: dict[str, list] = {}
        for asset in assets_dict.get("assets", []):
            for cid in asset.get("used_in_cards", []):
                card_assets.setdefault(cid, []).append(asset)

        cover_dict = draft_dict.get("cover", {})

        # 渲染每张卡片
        card_htmls: list[str] = []
        for card in layout_dict.get("cards", []):
            cid = card.get("card_id", "")
            card_template_type = card.get("template", "")
            card_blocks_for_card = card_blocks.get(cid, [])
            # conclusion 卡片若没有 card-surface 文案块，回退到最后一个 body 块
            if not card_blocks_for_card and card_template_type == "conclusion" and body_blocks:
                card_blocks_for_card = [body_blocks[-1]]
            card_data = {
                "card_id": cid,
                "card_heading": card.get("key_message", "")
                if cid != "card_1"
                else cover_dict.get("main_title", ""),
                "key_message": card.get("key_message", ""),
                "blocks": card_blocks_for_card,
                "assets": card_assets.get(cid, []),
            }
            # 封面卡片特殊处理：用 cover 数据
            if cid == "card_1":
                card_data["card_heading"] = cover_dict.get("main_title", "")
                card_data["key_message"] = cover_dict.get("subtitle", {}).get(
                    "text", ""
                )
            card_htmls.append(
                self.render_card_html(
                    card_data,
                    template_name,
                    design_token,
                    layout_card=layout_card_map.get(cid, {}),
                    cover=cover_dict,
                    content_type_label=content_type_label,
                )
            )

        page_tpl = self.env.get_template("_fallback_page.html.j2")
        return page_tpl.render(
            card_htmls=card_htmls,
            design_token=design_token,
            cover=cover_dict,
            body_blocks=body_blocks,
            tags=draft_dict.get("tags", []),
        )

    # ------------------------------------------------------------------
    # PNG 截图
    # ------------------------------------------------------------------
    def render_png(
        self,
        html_content: str,
        output_path: str,
        width: int = 1080,
        height: int = 1440,
    ) -> str:
        """用 Playwright 截图为 PNG。未安装时降级为只保存 HTML。

        返回实际产出的文件路径（PNG 或降级的 HTML）。
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # 始终保存一份 HTML，便于降级与排查
        html_path = output.with_suffix(".html")
        html_path.write_text(html_content, encoding="utf-8")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print(
                "[Renderer] Playwright 未安装，降级为只生成 HTML: "
                f"{html_path}"
            )
            return str(html_path)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html_content, wait_until="load")
                page.screenshot(path=str(output), full_page=False)
                browser.close()
            return str(output)
        except Exception as e:
            print(
                f"[Renderer] Playwright 截图失败({e})，降级为 HTML: {html_path}"
            )
            return str(html_path)


# 模块级便捷实例（无状态，可复用）
_default_renderer: Optional[Renderer] = None


def _get_default_renderer() -> Renderer:
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = Renderer()
    return _default_renderer


def render_html(
    layout_spec: LayoutSpec,
    draft: Draft,
    asset_manifest: AssetManifest,
    design_token: dict,
    template_name: str = None,
) -> str:
    """模块级便捷函数：渲染整页 HTML。"""
    return _get_default_renderer().render_html(
        layout_spec, draft, asset_manifest, design_token, template_name
    )


def render_png(
    html_content: str,
    output_path: str,
    width: int = 1080,
    height: int = 1440,
) -> str:
    """模块级便捷函数：HTML 截图为 PNG。"""
    return _get_default_renderer().render_png(
        html_content, output_path, width, height
    )


def render_card_html(
    card_data: dict,
    template_name: str,
    design_token: dict,
    layout_card: dict = None,
    cover: dict = None,
    content_type_label: str = "",
) -> str:
    """模块级便捷函数：渲染单张卡片 HTML。"""
    return _get_default_renderer().render_card_html(
        card_data,
        template_name,
        design_token,
        layout_card=layout_card,
        cover=cover,
        content_type_label=content_type_label,
    )
