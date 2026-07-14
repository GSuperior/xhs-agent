# 小红书 AI 内容 Agent 设计方案 v4.4

> 配套文档：`style_rules.md` v2.4（风格宪法，冻结版本）
> v4.4 变更：Reviewer Schema增加failed状态+issue_type加safety+route_to加failed（仅用于不可恢复问题）；状态转移表修正"严重事实错误→FAILED"为"涉及机密/安全/无法恢复的严重事实问题→FAILED"，可修复事实错误改走RESEARCHING补研；Reference Validator扩大覆盖范围（12类引用点全检：evidence_pack.source_ids/context_source_ids/snippets+card_outline.editorial_thesis/cards.claim_refs/thesis_ref+draft.blocks/titles/cover全字段）+流程门禁（OUTLINING和DRAFTING后必检）。
> v4.3 变更：修正Controller图超预算路由；HUMAN_REVIEW状态数据改为action_routes映射；discovery_candidates/topic_brief增加topic_subtype字段+条件校验；素材落盘时间顺序修正。
> v4.2 变更：补全HUMAN_REVIEW恢复路径+状态数据；修正超预算路由；修正趋势Claim与博主判断冲突；model_review归入comparison_review+topic_subtype；明确HARD与FAILED关系；Phase1A验收改为2类各5个样本；封面card_1固定统一编号；Phase1A素材source限制+落盘校验；17态验收描述修正。
> v4.1 变更：状态机17态；删除creator provenance；拆分angle_hypothesis/editorial_thesis；内容规划Agent只输出内容意图；Block Schema加条件校验；标题封面结构化；修正Reference Validator；Fetch保存来源快照；Reviewer结果pass时null；增加HUMAN_REVIEW/FAILED；content_type统一枚举；Source Schema调整；增加asset_manifest。
> **冻结版本**，与 style_rules v2.4 共同作为开发基线。

---

## 一、Agent 定位

帮博主「AI产品经理GSuperior」完成**日更小红书 AI 内容的产前闭环**：
选题发现 → 角度确认 → 研究取证 → 证据审核 → 大纲确认 → 文案 → 内容审核 → 视觉规划 → 布局审核 → 渲染 → 渲染校验 → 终稿确认。

**不做的事**：
- ❌ 不自动发布到小红书（人工发布）
- ❌ 不替博主做最终决策
- ❌ 不凭热点标题直接写内容（必须先建证据包）
- ❌ Controller 不自主生成内容（只做确定性流程控制）
- ❌ 不做登录态API+签名破解（合规风险）
- ❌ 研究取证Agent不生成creator观点（博主观点走editorial_thesis，由内容规划Agent生成）

---

## 二、整体架构

### 架构：1 确定性 Controller + 6 LLM Agent + 独立工具层

```
┌─────────────────────────────────────────────────────────┐
│              交互层（CLI / 后期 Streamlit）              │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│        确定性 Python Controller（不是 LLM Agent）        │
│  状态机(17态) ｜ 确认节点 ｜ 依赖管理 ｜ 重试预算 ｜ 日志  │
│  用户修改→LLM分类意图→识别受影响Artifact→依赖图失效      │
│  →按白名单route_to重跑（不自由跳转）                     │
│  超预算路由：研究/Evidence/大纲阶段→HUMAN_REVIEW          │
│              文案/布局阶段轻微问题→标记quality_limited继续 │
│              已有完整终稿后的轻微问题→FINAL_CONFIRMATION  │
│              核心证据不足→HUMAN_REVIEW                    │
│              不可恢复的事实/安全/产物问题→FAILED          │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 1.选题发现   │  │ 2.研究取证   │  │ 3.内容规划   │
│   与策划     │  │   Agent      │  │   Agent      │
│   Agent      │  │              │  │              │
│ 产出:        │  │ 产出:        │  │ 产出:        │
│ discovery_   │  │ evidence_   │  │ card_       │
│ candidates  │  │ pack        │  │ outline     │
│ selected_   │  │ (不含       │  │ (含         │
│ topic       │  │  creator)   │  │  editorial_ │
│ topic_brief │  │              │  │  thesis)    │
│ (含angle_   │  │              │  │              │
│  hypothesis)│  │              │  │ 内容意图     │
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 4.文案Agent  │  │ 5.视觉规划   │  │ 6.Reviewer   │
│              │  │   Agent      │  │   Agent      │
│ 产出:        │  │ 产出:        │  │ 三模式：     │
│ draft        │  │ layout_spec  │  │ Evidence/    │
│ (block结构   │  │ + asset_     │  │ Content/     │
│  +标题封面   │  │  manifest    │  │ Layout       │
│  结构化)     │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                      工具层                              │
│  Collectors ｜ Search/Fetch（纯文本+来源快照，防注入）   │
│  Schema Validator（字段/枚举/格式/字数/Block条件校验）   │
│  Reference Validator（claim_ref引用链完整性）            │
│  Jinja2 Renderer（自动转义+asset_manifest）｜ Playwright │
│  Render Validator（DOM溢出/尺寸/行数/遮挡）             │
│  Artifact Store（版本化存储）｜ Logger（决策级日志）     │
└─────────────────────────────────────────────────────────┘
```

### 各角色边界

| 模块 | 应负责 | 不应负责 |
|---|---|---|
| Controller | 状态调度、确认节点、依赖管理、重试预算、日志、白名单路由、超预算分流(FINAL/HUMAN_REVIEW/FAILED) | 自主生成内容、自由跳转 |
| 选题发现与策划Agent | 候选去重、角度拓展、价值判断、排序、angle_hypothesis | 直接抓取网页、生成creator观点 |
| 研究取证Agent | 搜索策略、证据提取、claim组织(仅外部) | 写文案、生成creator观点、访问敏感信息 |
| 内容规划Agent | 卡片叙事(内容意图)、图文分工、editorial_thesis、阅读节奏 | 写具体文案(headline/body)、修改事实 |
| 文案Agent | 标题、正文、卡片文字(block结构)、标题封面结构化 | 增加证据包外事实 |
| 视觉规划Agent | 选模板、生成layout_spec、管理asset_manifest | 自由生成HTML、直接下载URL |
| Reviewer Agent | 语义和质量判断、结构化结果+route_to、引用rule_id | 直接改写产物、自由跳转 |
| Schema Validator | 字段/枚举/格式/字数/Block条件校验 | 语义判断 |
| Reference Validator | claim_ref/supporting_claim_refs引用链完整性 | 判断claim是否支持这句话 |
| Render Validator | DOM/尺寸/溢出/遮挡确定性校验 | 美观度评价 |
| Renderer工具 | 按layout_spec+asset_manifest生成HTML+PNG | 判断内容好坏 |

---

## 三、状态机（17态）

```
INIT
→ DISCOVERING              # 选题发现与策划Agent：热点扫描/线索拓展+策划
→ TOPIC_ANGLE_CONFIRMATION # 【用户确认节点1：选题+核心角度(angle_hypothesis)】
→ RESEARCHING              # 研究取证Agent：建证据包(仅外部claim)
→ EVIDENCE_REVIEW          # Reviewer(Evidence模式)+Reference Validator+来源快照核对
→ OUTLINING                # 内容规划Agent：卡片大纲(内容意图)+editorial_thesis
→ OUTLINE_CONFIRMATION     # 【用户确认节点2：卡片大纲+editorial_thesis】
→ DRAFTING                 # 文案Agent：block结构+标题封面结构化(含claim_refs)
→ CONTENT_REVIEW           # Reviewer(Content模式)+Reference Validator
→ VISUAL_PLANNING          # 视觉规划Agent：layout_spec+asset_manifest
→ LAYOUT_REVIEW            # Reviewer(Layout模式)：基于layout_spec检查
→ RENDERING                # Renderer工具：HTML+PNG
→ RENDER_VALIDATION        # Render Validator：DOM/尺寸/溢出/遮挡
→ FINAL_CONFIRMATION       # 【用户确认节点3：终稿，人工看PNG美观度】
→ COMPLETED

异常状态：
→ HUMAN_REVIEW             # 核心证据不足/渲染失败但有HTML/需人工介入
→ FAILED                   # 机密泄露/安全风险/无可用产物/无法恢复的严重事实问题
```

> Phase 3 接入多模态模型后，在 RENDER_VALIDATION 后增加 VISUAL_REVIEW，变18态。

### 完整状态转移表（含回退和异常路由）

| 当前状态 | 结果 | 下一状态 | 重试预算 |
|---|---|---|---|
| DISCOVERING | 完成 | TOPIC_ANGLE_CONFIRMATION | - |
| TOPIC_ANGLE_CONFIRMATION | 用户确认 | RESEARCHING | - |
| RESEARCHING | 完成 | EVIDENCE_REVIEW | - |
| EVIDENCE_REVIEW | 缺证据(轻微) | RESEARCHING（补研） | MAX_SUPPLEMENT_RESEARCH |
| EVIDENCE_REVIEW | 通过 | OUTLINING | - |
| EVIDENCE_REVIEW | 核心证据不足(严重) | HUMAN_REVIEW | - |
| OUTLINING | 完成 | OUTLINE_CONFIRMATION | - |
| OUTLINE_CONFIRMATION | 用户确认 | DRAFTING | - |
| DRAFTING | 完成 | CONTENT_REVIEW | - |
| CONTENT_REVIEW | 文案问题 | DRAFTING | MAX_REVISE_COPY |
| CONTENT_REVIEW | 结构问题 | OUTLINING | MAX_REVISE_OUTLINE |
| CONTENT_REVIEW | 新事实缺证据 | RESEARCHING | MAX_SUPPLEMENT_RESEARCH |
| CONTENT_REVIEW | 可修复的事实错误或证据错误 | RESEARCHING | MAX_SUPPLEMENT_RESEARCH |
| CONTENT_REVIEW | 通过 | VISUAL_PLANNING | - |
| CONTENT_REVIEW | 涉及机密、安全或无法恢复的严重事实问题 | FAILED | - |
| VISUAL_PLANNING | 完成 | LAYOUT_REVIEW | - |
| LAYOUT_REVIEW | 布局问题 | VISUAL_PLANNING | MAX_REVISE_LAYOUT |
| LAYOUT_REVIEW | 通过 | RENDERING | - |
| RENDERING | 完成 | RENDER_VALIDATION | - |
| RENDERING | 渲染失败 | RENDERING | MAX_RENDER_RETRY |
| RENDER_VALIDATION | 渲染失败 | RENDERING | MAX_RENDER_RETRY |
| RENDER_VALIDATION | 通过 | FINAL_CONFIRMATION | - |
| RENDER_VALIDATION | 渲染失败但有HTML | HUMAN_REVIEW | - |
| FINAL_CONFIRMATION | 用户修改 | 按依赖图回退（见第八节路由表） | - |
| FINAL_CONFIRMATION | 用户确认 | COMPLETED | - |
| 研究/Evidence/大纲阶段 | 轻微问题超预算 | HUMAN_REVIEW | - |
| 文案或布局阶段 | 轻微问题超预算 | 继续下游并标记 quality_limited | - |
| 已有完整终稿后 | 仍有轻微问题 | FINAL_CONFIRMATION（标记质量限制） | - |
| 任一节点 | 核心证据不足 | HUMAN_REVIEW | - |
| 任一节点 | 涉及机密、安全或无法恢复的严重事实问题 | FAILED | - |
| 任一节点 | 无可用产物 | FAILED | - |

### 异常状态说明

| 状态 | 触发条件 | 处理 |
|---|---|---|
| HUMAN_REVIEW | 核心证据不足/渲染失败但有HTML/研究或大纲阶段超预算/需人工判断 | 暂停流程，输出状态数据（见下方），等待人工介入后按恢复路由继续 |
| FAILED | 机密泄露/安全风险/无可用产物/无法恢复的严重事实问题 | 终止流程，输出失败原因和日志，不产出可发布内容 |

### HUMAN_REVIEW 状态数据

```json
{
  "blocking_reason": "核心Claim缺少可靠来源",
  "required_action": "用户补充来源或接受证据边界",
  "action_routes": {
    "supplement_source": "RESEARCHING",
    "accept_limitation": "OUTLINING",
    "terminate": "FAILED"
  }
}
```

> action_routes 动态生成：证据问题用上方示例；素材/HTML问题用 `{"fix_asset": "RENDERING", "accept_limited_final": "FINAL_CONFIRMATION", "terminate": "FAILED"}`。Controller 无需同时维护 resume_state 和外部恢复路由表。

### HUMAN_REVIEW 恢复路由

| 人工处理结果 | 下一状态 |
|---|---|
| 补充来源或材料 | RESEARCHING |
| 接受当前证据边界 | OUTLINING |
| 修复素材或HTML | RENDERING |
| 接受已有受限终稿 | FINAL_CONFIRMATION |
| 无法继续 | FAILED |

---

## 四、6个 LLM Agent 详解

### 1. 选题发现与策划 Agent

**职责**：发现候选 + 价值判断 + 角度策划。

**入口A - 热点扫描**：调 Collector 采集多源，产出 `discovery_candidates.json`（5个轻量候选）：
```json
{
  "candidates": [
    {
      "topic_id": "t001", "title": "", "source_urls": [],
      "published_at": "", "what_happened": "",
      "target_audience": "", "product_angle": "", "why_now": "",
      "shareability": 0, "evidence_quality": 0,
      "technical_difficulty": 0,
      "lifecycle": "breaking|trending|evergreen|series",
      "valid_until": "2026-07-16",
      "refresh_required": true,
      "content_type": "product_breakdown",
      "content_type_label": "产品拆解",
      "topic_subtype": null
    }
  ]
}
```

**入口B - 线索拓展**：把用户输入拓展成3-5种角度。

**用户选中后**，产出 `selected_topic.json` → 再生成详细 `topic_brief.json`：
```json
{
  "topic": "", "target_reader": "", "reader_problem": "",
  "one_sentence_value": "", "core_angle": "",
  "content_type": "product_breakdown",
  "content_type_label": "产品拆解",
  "topic_subtype": null,
  "hook": "",
  "expected_takeaway": [], "differentiation": "",
  "avoid": [], "research_questions": [],
  "angle_hypothesis": {
    "statement": "这次更新的主要价值可能是降低AI工具使用门槛",
    "questions_to_verify": ["是否真的降低了操作步骤", "是否只面向付费用户"]
  }
}
```

> angle_hypothesis 是研究前的待验证角度，此时无 Claim ID。避免研究结果与前置判断不一致时 Agent 强行找支持材料。

**核心验收**：一句话价值——"用户看完比只看新闻标题多知道什么？" 说不清不进研究。

### 2. 研究取证 Agent

**职责**：针对 research_questions 定向搜索，构建事实底座。**不生成 creator 观点**（provenance 不含 creator）。

**信息源选择**（按 claim 类型，非固定全局优先级）：
- 官方来源优先验证：功能、参数、发布时间
- 独立测试用于验证：效果
- 用户和社区内容用于验证：体验、争议、使用问题
- 媒体/招聘/融资用于验证：行业趋势

**产出 `evidence_pack.json`**：
```json
{
  "topic": "", "event_time": "",
  "claims": [
    {
      "claim_id": "c1",
      "claim": "",
      "epistemic_type": "factual|interpretive|projective|experiential",
      "content_role": "core|background|comparison|limitation|case|trend",
      "provenance": "official|media|community|user",
      "source_ids": ["s1"],
      "context_source_ids": [],
      "evidence_snippets": [
        {"source_id": "s1", "snippet": "原文短摘录", "location": "Release Notes / Section 2"}
      ],
      "confidence": "high|medium|low",
      "confidence_reason": "",
      "time_scope": "截至2026-07-13",
      "applicability": "仅适用于Pro版本"
    }
  ],
  "sources": [
    {
      "source_id": "s1", "publisher": "", "url": "",
      "published_at": null, "updated_at": null,
      "accessed_at": "2026-07-14T10:20:00",
      "version_or_commit": null,
      "source_type": "primary|media|user|community",
      "snapshot_ref": "sources/s1.txt",
      "content_hash": "sha256:..."
    }
  ],
  "uncertainties": [], "content_opportunities": []
}
```

**关键规则**：
- provenance 不含 creator（博主观点走 editorial_thesis）
- source_ids 中每个 source 必须有对应 evidence_snippet
- 背景来源放 context_source_ids，不要求 snippet
- Source 保存来源快照（snapshot_ref + content_hash），供 Evidence Reviewer 核对原文

**证据要求分级**（按 epistemic_type + content_role）：

| Claim 类型 | 最低证据要求 |
|---|---|
| 官方已发布功能（factual+core） | 1个直接一手来源 |
| 精确数字或参数（factual） | 1个权威一手来源，必要时交叉核验 |
| 产品效果判断（interpretive） | 官方信息 + 独立体验/测试 |
| 竞品比较（comparison） | 每个对象一手资料，指标口径一致 |
| 外部趋势/预测（trend/projective） | 至少2个独立来源；证据不足时写入 uncertainties，不作为核心 Claim |
| 用户体验（experiential） | 标明样本来源，不可直接泛化 |

> 博主趋势判断不放入 evidence_pack，而是写入 card_outline 的 editorial_thesis，通过 supporting_claim_refs 关联外部 Claim，用 certainty 标记判断置信度。外部 Claim 不可通过"标记为博主判断"降低证据要求。

**数量预算**：默认5-10条核心claim，以覆盖研究问题为结束条件。

### 3. 内容规划 Agent

**职责**：设计卡片阅读路径，把证据包组织成图文结构。**只输出内容意图，不写具体文案**。根据 Evidence 生成 editorial_thesis。

**产出 `card_outline.json`**（card_1 封面也包含在 cards 数组中）：
```json
{
  "editorial_thesis": {
    "statement": "我认为这次更新真正降低的是首次使用门槛，但没有显著降低专业使用成本。",
    "supporting_claim_refs": ["c2", "c5"],
    "certainty": "medium"
  },
  "cards": [
    {
      "card_id": "card_1",
      "purpose": "封面",
      "key_message": "AI原型设计开始降低专业门槛",
      "key_points": [],
      "claim_refs": ["c2"],
      "thesis_ref": null,
      "visual_type": "cover",
      "max_chars": 30
    },
    {
      "card_id": "card_3",
      "purpose": "解释为什么值得关注",
      "key_message": "使用门槛降低，但适用范围有限",
      "key_points": ["操作步骤减少", "仅面向Pro用户"],
      "claim_refs": ["c2", "c3"],
      "thesis_ref": null,
      "visual_type": "comparison",
      "max_chars": 90
    },
    {
      "card_id": "card_6",
      "purpose": "PM判断",
      "key_message": "降低的是首次使用门槛，不是专业成本",
      "key_points": [],
      "claim_refs": ["c2", "c5"],
      "thesis_ref": "editorial_thesis",
      "visual_type": "conclusion",
      "max_chars": 90
    }
  ]
}
```

> thesis_ref 只能为 "editorial_thesis" 或 null。card_6（PM判断页）使用 thesis_ref="editorial_thesis"。

> 内容规划 Agent 负责"讲什么"（purpose/key_message/key_points），文案 Agent 负责"具体怎么表达"（headline/body）。

**默认6张卡片**（复杂题升8张），**card_1 固定为封面，card_2~card_6 为内容页**：

| 卡片 | 作用 | 主要 content_role | 允许的 epistemic_type |
|---|---|---|---|
| card_1（封面） | 封面：冲突、价值或结论 | core | factual/interpretive/projective |
| card_2 | 发生了什么 | core/background | factual |
| card_3 | 为什么值得关注 | core/background/trend | factual/interpretive |
| card_4 | 核心机制或产品逻辑 | core/comparison | factual/interpretive |
| card_5 | 用户场景或案例 | case | factual/experiential |
| card_6 | PM判断（editorial_thesis） | core/trend | interpretive/projective |
| card_7（可选） | 局限、误区或争议 | limitation | factual/interpretive/experiential |
| card_8（可选） | 总结、行动建议 | core | interpretive/projective |

> card_1 固定为封面，card_outline 和 draft 的 cover 都引用 card_id="card_1"。thesis_ref 只能为 "editorial_thesis" 或 null，PM判断页（card_6）使用 thesis_ref="editorial_thesis"。

**图文分工约束**：
- 图片承担：框架、结论、对比、重点
- 正文承担：补充说明、个人判断、语气
- 不把图片文字原样复制到正文
- 每张图片只讲一个中心信息
- 卡片中的外部事实只能来自 claim_refs 指定的 Claim。卡片可以通过 thesis_ref 引用 editorial_thesis，表达经用户确认的博主判断。editorial_thesis 的事实依据由其自身的 supporting_claim_refs 管理。
- **三字段语义定义**：
  - `claim_refs`：该卡片直接陈述或展示的外部事实。card_6 如果只表达观点、不直接展示事实，允许为空。
  - `thesis_ref`：该卡片是否承载 editorial_thesis；只能为 "editorial_thesis" 或 null。
  - `editorial_thesis.supporting_claim_refs`：支撑博主核心判断的外部 Claim。

### 4. 文案 Agent

**职责**：把卡片大纲（内容意图）扩写成普通人愿意读的正文和卡片文案。

**角色**：懂AI产品的内容编辑（不是技术专家）。

**规则**：从用户问题切入 / 术语首次出现用人话解释 / 少讲参数多讲变化 / 观点明确 / 不营销腔 / 不堆emoji / 不夸大 / 保留个人判断 / 正文比研究材料短 / 遵循VOICE规则。

**产出 `draft.json`**（block结构 + 标题封面结构化）：
```json
{
  "post_title_candidates": [
    {
      "text": "拆一个AI产品：Aippy",
      "statement_type": "creator_opinion",
      "claim_refs": [],
      "supporting_claim_refs": ["c1"]
    }
  ],
  "cover": {
    "card_id": "card_1",
    "series_label": "拆一个AI产品",
    "main_title": "Aippy",
    "subtitle": {
      "text": "AI原型设计开始降低专业门槛",
      "statement_type": "mixed",
      "claim_refs": ["c2"],
      "supporting_claim_refs": []
    }
  },
  "blocks": [
    {
      "block_id": "b1",
      "surface": "body",
      "card_id": null,
      "text": "这项功能目前只对Pro用户开放，但我认为这其实是聪明的定价策略。",
      "statement_type": "mixed",
      "claim_refs": ["c3"],
      "supporting_claim_refs": []
    },
    {
      "block_id": "b2",
      "surface": "card",
      "card_id": "card_3",
      "text": "操作步骤减少，但仅面向Pro用户",
      "statement_type": "external_claim",
      "claim_refs": ["c2", "c3"],
      "supporting_claim_refs": []
    }
  ],
  "tags": ["#ai", "#AI人工智能", "..."]
}
```

**Block 条件校验**：

| 条件 | 规则 |
|---|---|
| surface=body | card_id 必须为 null |
| surface=card | card_id 必须存在 |
| statement_type=external_claim | claim_refs 不能为空 |
| statement_type=mixed | claim_refs 不能为空 |
| statement_type=creator_opinion | claim_refs 可空，有事实依据时填 supporting_claim_refs |

> 标题和封面副标题如果包含外部事实（如数字、结论），必须有 claim_refs。

### 5. 视觉规划 Agent

**职责**：选模板 + 生成 layout_spec + 管理 asset_manifest，**不自由生成HTML，不直接下载URL**。

**产出 `layout_spec.json` + `asset_manifest.json`**：

layout_spec:
```json
{
  "template": "product_breakdown",
  "cards": [
    {
      "card_id": "card_3",
      "layout": "two_column_comparison",
      "hierarchy": ["headline", "key_point", "comparison"],
      "emphasis": ["左侧旧方式", "右侧新方式"],
      "icon_keys": ["before", "after"],
      "asset_refs": ["a1"]
    }
  ]
}
```

asset_manifest:
```json
{
  "assets": [
    {
      "asset_id": "a1",
      "type": "logo|screenshot|icon|illustration",
      "source": "user_provided|library|generated",
      "source_url": "",
      "local_ref": "assets/a1.png",
      "license_note": "",
      "used_in_cards": ["card_1"]
    }
  ]
}
```

> **Phase 1A 限制**：asset.source 只能为 user_provided / library / generated（不含 official 远程下载）。
>
> **素材落盘时间顺序**：
> 1. 用户上传/素材库准备素材 → 生成 `available_assets.json`（轻量输入，只含 asset_id/type/source/local_ref）
> 2. VISUAL_PLANNING 从 available_assets 中选择 asset_id → 生成 asset_manifest.json
> 3. 进入 RENDERING 前检查所有 local_ref 是否存在
>
> 规则：视觉规划 Agent 只能选择 available_assets 中已存在的素材；asset_manifest 中所有 local_ref 必须在进入 RENDERING 前通过文件存在性校验。generated 类型只有在本地文件已生成并进入 available_assets 后才能使用。Phase 1A 不需要新增 Asset Resolver，official 远程下载放 Phase 1B。

**available_assets.json（轻量输入）**：
```json
{
  "available_assets": [
    {
      "asset_id": "a1",
      "type": "logo",
      "source": "user_provided",
      "local_ref": "assets/a1.png"
    }
  ]
}
```

**只做**：模板选择 / 布局类型 / 信息层级 / 强调点 / 图标key / 素材引用。
**不做**：写HTML代码 / 生成PNG / 直接下载URL。

### 6. Reviewer Agent（一个Agent，三模式运行）

**结构化结果**（统一格式）：
```json
{
  "status": "pass|revise|blocked|failed",
  "issue_type": "evidence|outline|copy|layout|render|safety|null",
  "route_to": "researching|outlining|drafting|visual_planning|rendering|human_review|failed|null",
  "issues": [
    {
      "rule_id": "CONTENT_003",
      "location": "block_b3",
      "problem": "出现未引用数字",
      "severity": "major",
      "suggested_action": "补充claim_refs或删除数字"
    }
  ],
  "severity": "none|minor|major|blocking"
}
```

**规则**：
- `pass`：issue_type=null, route_to=null
- `revise`：必须路由到可返工状态（researching/outlining/drafting/visual_planning/rendering）
- `blocked`：route_to=human_review
- `failed`：route_to=failed, severity=blocking，仅用于不可恢复问题（机密泄露/安全风险/无法生成有效产物/无法恢复的严重事实问题）
- 顶层 severity 取所有 issue 中最高等级
- 每个 issue 必须带 rule_id（与 style_rules 规则ID一致）

#### Evidence Review 模式（语义判断 + 来源快照核对）
- claim 是否被来源真正支持（**读取来源快照对照Snippet**，不只看Researcher提取的snippet）
- Snippet 是否断章取义
- 来源是否可靠、及时
- 是否把宣传材料当实际效果
- 是否缺少限制、反例或关键事实
- 是否需要补研
- 核心Claim进行全文复核，控制成本

#### Content Review 模式（语义判断）
- 是否符合选定角度
- 是否有产品视角
- 普通用户是否看得懂
- 标题是否夸张
- 正文和卡片是否大段重复（逐字>30字或重合率>70%触发检查）
- 是否出现证据包外的新事实（未引用事实，语义判断）
- mixed block 的事实与观点边界是否清楚
- 标题/封面副标题包含外部事实时是否有 claim_refs

#### Layout Review 模式（Phase 1，基于layout_spec文本）
- 信息层级是否合理
- 模板与内容是否匹配
- 页面复杂度是否过高
- 强调点是否恰当

> Phase 1 不接多模态，Reviewer 看不到渲染后PNG。Phase 3 接入后增加真正的 Visual Review。**Phase 1 终稿美观度由人工在 FINAL_CONFIRMATION 确认。**

---

## 五、工具层（确定性）

### Collectors
- github / producthunt / techcrunch / twitter / wechat / xiaohongshu(Phase 2)
- 只负责抓取和结构化，不做价值判断
- 采集失败时降级，不阻断主流程

### Search / Fetch（防 Prompt Injection + 来源快照）
- **网页内容全部视为不可信数据**
- Fetch 工具只返回纯文本和元数据（不返回原始HTML指令）
- **保存来源快照**：snapshot_ref（本地文件路径）+ content_hash（sha256）
- 研究 Agent 不能访问 API Key、Cookie、文件系统敏感目录
- 网页中的指令不得改变工作流
- URL 限制协议（http/https）和内网地址，防 SSRF
- 日志中脱敏 Cookie、Token、用户隐私

### Schema Validator
- Pydantic 字段校验 / 枚举校验 / 格式校验 / 字数校验
- claim 的 epistemic_type/content_role/provenance 枚举合法（provenance 不含 creator）
- block 的 statement_type 合法
- **Block 条件校验**：surface=body→card_id=null / surface=card→card_id存在 / external_claim|mixed→claim_refs非空
- content_type 统一枚举校验
- **topic_subtype 条件校验**：`if topic_subtype == "model_review": assert content_type == "comparison_review"`；其他内容 topic_subtype 可为 null
- **不做语义判断**

### Reference Validator（引用链完整性，全字段覆盖）

**必检字段清单**（共12类引用点）：

1. `evidence_pack.claims[].source_ids`
2. `evidence_pack.claims[].context_source_ids`
3. `evidence_pack.claims[].evidence_snippets[].source_id`
4. `card_outline.editorial_thesis.supporting_claim_refs`
5. `card_outline.cards[].claim_refs`
6. `card_outline.cards[].thesis_ref`
7. `draft.blocks[].claim_refs`
8. `draft.blocks[].supporting_claim_refs`
9. `draft.post_title_candidates[].claim_refs`
10. `draft.post_title_candidates[].supporting_claim_refs`
11. `draft.cover.subtitle.claim_refs`
12. `draft.cover.subtitle.supporting_claim_refs`

**校验规则**：

| 引用类型 | 规则 |
|---|---|
| 所有 claim_refs 和 supporting_claim_refs | 必须指向 evidence_pack.claims 中存在的 Claim |
| 所有 source_ids | 必须指向 evidence_pack.sources 中存在的 Source |
| 所有 context_source_ids | 必须指向 evidence_pack.sources 中存在的 Source（不强制要求 snippet） |
| source_ids 中的每个 Source | 必须在 claim.evidence_snippets 中有对应 source_id 的 snippet |
| thesis_ref | 只能为 "editorial_thesis" 或 null；非空时 card_outline 中必须存在 editorial_thesis |
| source | 必须有 URL/发布方/来源类型，accessed_at 必须存在 |

**流程门禁**：

- OUTLINING → Schema Validator → Reference Validator → OUTLINE_CONFIRMATION（大纲确认前校验 card_outline 引用链）
- DRAFTING → Schema Validator → Reference Validator → CONTENT_REVIEW（文案后校验 draft 引用链）

> **不做语义判断**（不判断 claim 是否真正支持这句话，语义核验由 Reviewer + 来源快照完成）。

### Jinja2 Renderer
- 按 layout_spec + 固定模板填充 HTML
- 应用 Design Token（从 `config/design_token.json` 读取，以 style_rules 定义为准）
- **开启自动转义**（防 XSS / 注入）
- 图标和模板使用白名单
- **素材通过 asset_manifest 引用**，不直接下载任意 URL

### Playwright Screenshot
- HTML → PNG

### Render Validator
- HTML 字段完整性
- DOM 溢出检查
- 尺寸 1080×1440
- 行数限制
- 元素遮挡检查
- **不做美观度评价**（人工或Phase 3多模态）

### Artifact Store（版本化存储）
- **不覆盖同名文件**，按版本存储：
  ```
  runs/20260713_143012_lovart_a82f/
  └── artifacts/
      ├── evidence_pack/v1.json
      ├── evidence_pack/v2.json
      ├── draft/v1.json
      └── ...
  ```
- `artifacts.json` 保存当前生效版本和依赖关系

### Logger
- 决策级日志（见第七节）

---

## 六、三模式设计（Deep 前后置）

### Daily 模式
- 扫描热点，输出 `discovery_candidates.json`（5候选），不生成完整笔记

### Create 模式（默认）
- 完整流程，补研最多 MAX_SUPPLEMENT_RESEARCH 次

### Deep 模式（前置 + 后置触发）

**前置触发**（研究前）：模型评测 / 多产品对比 / 争议话题 / 高风险强时效 / 用户 `--deep`

**后置升级**（Evidence Review 阶段）：核心结论单一弱来源 / 关键来源冲突 / 缺反方证据 / 指标口径不一致 / Reviewer判断证据不足

Deep 模式补研最多 MAX_SUPPLEMENT_RESEARCH_DEEP 次。

---

## 七、文件式状态与决策级日志

### Run 目录结构
```
runs/
└── 20260713_143012_lovart_a82f/      # Run ID：日期_时间_主题_随机ID
    ├── user_input.json
    ├── discovery_candidates.json     # 5个轻量候选（Daily模式）
    ├── selected_topic.json           # 用户选中的主题
    ├── topic_brief.json              # 含 angle_hypothesis
    ├── evidence_pack.json            # 仅外部claim，不含creator
    ├── card_outline.json             # 含 editorial_thesis + 卡片内容意图
    ├── draft.json                    # block结构 + 标题封面结构化
    ├── layout_spec.json
    ├── available_assets.json         # 可用素材清单（VISUAL_PLANNING输入）
    ├── asset_manifest.json           # 视觉规划选中的素材清单
    ├── review_evidence.json
    ├── review_content.json
    ├── review_layout.json
    ├── final_note.json
    ├── sources/                      # 来源快照
    │   ├── s1.txt
    │   └── ...
    ├── assets/                       # 视觉素材
    │   ├── a1.png
    │   └── ...
    ├── artifacts/                    # 版本化存储
    │   ├── evidence_pack/v1.json
    │   ├── evidence_pack/v2.json
    │   ├── draft/v1.json
    │   └── ...
    ├── artifacts.json                # 当前生效版本+依赖图
    ├── output/                       # 渲染产物
    │   ├── cover.html / cover.png
    │   ├── content_1.html / content_1.png
    │   └── ...
    └── run_log.jsonl
```

### 决策级日志格式
```json
{
  "run_id": "20260713_143012_lovart_a82f",
  "stage": "evidence_review",
  "agent": "reviewer",
  "mode": "evidence",
  "input_refs": ["artifacts/evidence_pack/v2.json", "sources/s1.txt"],
  "output_ref": "review_evidence.json",
  "model": "deepseek-chat",
  "started_at": "2026-07-13T14:30:00",
  "duration_ms": 8200,
  "token_usage": {"input": 3400, "output": 900},
  "decision": {
    "status": "revise",
    "issue_type": "evidence",
    "route_to": "researching",
    "severity": "major"
  },
  "issues": [
    {"rule_id": "EVIDENCE_004", "location": "claim_c3", "problem": "Snippet与来源快照不一致", "severity": "major"}
  ],
  "warnings": ["缺少反方证据"],
  "status": "success"
}
```

### 重点分析指标

| 指标 | 定义 | 用途 |
|---|---|---|
| 用户修改选题比例 | 从首次候选到确认的修改率 | 判断热点推荐是否准确 |
| 大纲一次通过率 | 用户第一次查看后无需修改即确认 | 判断内容策划质量 |
| 补研触发率 | Evidence Review 触发补研的比例 | 判断前期研究是否充分 |
| 事实错误率 | 严重事实错误发生比例 | 判断Evidence机制效果 |
| 卡片文字超限率 | Render Validator 检出超限比例 | 判断模板约束是否合理 |
| 用户改写最多的部分 | 统计修改集中在哪个Artifact | 判断哪个Agent最需要优化 |
| 单篇耗时和Token | 排除用户等待的纯处理时间 | 判断成本 |
| 各阶段失败率 | 各状态进入HUMAN_REVIEW/FAILED的比例 | 定位系统瓶颈 |
| 最常违反的规则ID | 按rule_id统计违反频次 | 精准优化规则 |

---

## 八、局部重跑路由表

用户修改指令 → LLM 分类意图 → 识别受影响 Artifact → 判断字段变化 → 按依赖图失效 → 重跑。

| 用户修改 | 受影响Artifact | 重跑范围 |
|---|---|---|
| 从已有标题候选换一个（不改核心观点） | final_note | 标题规则校验→封面渲染→Render Validator（不跑完整Content Review） |
| 从已有标题候选换一个（改变核心观点/有夸大风险） | draft(标题部分) | 标题生成→Content Review→封面渲染 |
| 重新生成标题 | draft(标题部分) | 标题生成→Content Review→封面渲染 |
| 第3页表达太技术（文本长度未变） | draft(block) | 文案→Content Review→重新渲染第3页（不重跑视觉规划） |
| 第3页表达太技术（长度/结构/强调变化） | draft+layout_spec | 文案→Content Review→视觉规划→渲染第3页 |
| 第3页逻辑不清 | card_outline+draft | 内容规划→文案→Content Review→视觉规划→渲染 |
| 增加一个事实 | evidence_pack+下游 | 研究→Evidence Review→全部下游 |
| 调整卡片顺序 | card_outline+下游 | 内容规划→文案→Content Review→视觉规划→渲染 |
| 换模板或配色 | layout_spec+asset_manifest | 视觉规划→渲染→Render Validator |
| 正文缩短（不涉及卡片） | draft(body部分) | 文案→Content Review（无需重渲染卡片） |
| 修改核心角度 | topic_brief+全部下游 | 研究及全部下游失效（基本重来） |

**实现**：Artifact Store 记录 version + depends_on，修改时按依赖图失效下游，只重跑受影响部分。Controller 按 Reviewer 的 route_to 白名单路由。

---

## 九、三确认节点

### 节点1：选题+核心角度确认（TOPIC_ANGLE_CONFIRMATION）
Agent 展示：话题 / 为什么值得发 / 核心角度 / 一句话价值 / 可能风险 / angle_hypothesis。
用户：选择 / 修改 / 输入新话题。

### 节点2：卡片大纲确认（OUTLINE_CONFIRMATION）
Agent 展示：目标读者 / 一句话价值 / 3个标题方向 / 卡片大纲(6或8张，内容意图) / editorial_thesis / 内容亮点 / 事实边界。
用户确认 editorial_thesis 后才进文案。

### 节点3：终稿确认（FINAL_CONFIRMATION）
Agent 展示：标题候选 / 正文 / 卡片文案 / HTML+PNG预览路径 / 来源 / 审核结果。
**人工查看真实PNG确认美观度**（Phase 1 无多模态）。
用户用自然语言修改（见第八节路由表）。

---

## 十、技术选型与模型配置

### 技术栈

| 层 | 技术 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态全 |
| CLI | Typer | 类型友好 |
| LLM SDK | openai 兼容协议 | DeepSeek/通义/智谱都兼容 |
| 采集 | httpx + BeautifulSoup + 正则 | 异步轻量 |
| 模板渲染 | Jinja2（自动转义） | 固定模板填充+防注入 |
| 图片渲染 | Playwright | Python生态最顺 |
| 日志 | logging + JSON + jsonl | 结构化 |
| 状态 | 文件式 runs/ 目录（版本化） | 直观可调试 |
| 配置 | YAML + .env | key/cookie 走 .env |
| Schema | Pydantic | 契约约束+校验+Block条件校验 |

### 模型分配（配置化）

`config/models.yaml`：
```yaml
models:
  topic: default_model
  research: default_model
  planning: strong_model
  writing: writing_model
  visual_planning: default_model
  review: judge_model
  intent_classifier: default_model

model_endpoints:
  default_model: {provider: deepseek, model: deepseek-chat}
  strong_model: {provider: deepseek, model: deepseek-v3}
  writing_model: {provider: deepseek, model: deepseek-v3}
  judge_model: {provider: zhipu, model: glm-4}
```

**第一版策略**：只接1-2个模型（DeepSeek为主），所有角色先用 default_model，积累日志后再拆。

### Design Token

> Design Token 唯一来源：`config/design_token.json`，具体结构以 `style_rules.md` v2.4 第五部分 Schema 定义为准。agent_design.md 不保留副本。

---

## 十一、对第五轮设计师建议的取舍说明

### 完全采纳（19条全部采纳）

**P0必须修正**：
- ✅ 状态数修正：17态（INIT + 14业务态 + HUMAN_REVIEW + FAILED）
- ✅ 从 evidence_pack 删除 creator provenance，卡片6改为 editorial_thesis + supporting_claim_refs
- ✅ 拆分 angle_hypothesis（研究前，topic_brief）和 editorial_thesis（研究后，card_outline）
- ✅ 内容规划 Agent 只输出内容意图（purpose/key_message/key_points），文案 Agent 负责表达
- ✅ Block Schema 加 supporting_claim_refs + 条件校验（surface/card_id/statement_type 联动）
- ✅ 标题和封面文字结构化（带 claim_refs/supporting_claim_refs）
- ✅ 修正 Reference Validator（snippet 在 claim.evidence_snippets，source_ids 每个 source 必须有 snippet，背景来源放 context_source_ids）
- ✅ Source 增加快照（snapshot_ref/content_hash），Evidence Reviewer 核对来源原文
- ✅ Reviewer 结果 pass 时 issue_type/route_to 为 null，blocked 进 human_review，每个 issue 带 rule_id
- ✅ 增加 HUMAN_REVIEW 和 FAILED 状态

**公共枚举统一**：
- ✅ content_type 统一枚举 + content_type_label
- ✅ Design Token 以 style_rules 为唯一真源，agent_design 删除副本

**style_rules 缺失内容**（在 style_rules v2.1 中修正）：
- ✅ 补回各栏目正文结构蓝图
- ✅ 补充 IDENTITY_003 / VOICE_001 / VOICE_002 / VOICE_003
- ✅ 增加 STYLE_012（卡片字数）
- ✅ 定义 CONTENT_007"大段重复"阈值

**工程验收补充**：
- ✅ Source Schema 调整（published_at 可空，accessed_at 必填，加 updated_at/version_or_commit）
- ✅ 增加 asset_manifest.json（视觉素材清单）
- ✅ 验收指标补充样本量

### 不采纳
- 无。

---

## 十二、分阶段交付计划

### Phase 1A：内容质量闭环（最优先）

**目标**：验证"生成的内容是否真的值得发布"。

**信息源**：用户输入主题或链接（不做自动热点采集）

**模板**：2类（product_breakdown / trend_analysis）

**核心能力**：
- [ ] 项目脚手架 + 配置 + Pydantic Schema（claim三字段/block条件校验/标题封面结构化/asset_manifest）
- [ ] 确定性 Controller + 17态状态机 + 三确认节点 + 状态转移表 + 异常路由
- [ ] 重试预算控制（6个 MAX_* 配置）
- [ ] LLM 客户端（DeepSeek 单模型）
- [ ] 选题发现与策划Agent（仅线索拓展入口，输出 angle_hypothesis）
- [ ] 研究取证Agent（建证据包，仅外部claim，防 Prompt Injection，保存来源快照）
- [ ] Evidence Review（Reviewer + Reference Validator + 来源快照核对）
- [ ] 内容规划Agent（输出内容意图 + editorial_thesis）
- [ ] 文案Agent（block结构 + 标题封面结构化 + claim_refs）
- [ ] Content Review（Reviewer + Reference Validator）
- [ ] 视觉规划Agent（layout_spec + asset_manifest）
- [ ] Layout Review（Reviewer）
- [ ] Renderer工具（Jinja2自动转义 + Playwright + 2类模板 + asset_manifest引用）
- [ ] Render Validator
- [ ] Artifact Store（版本化）+ 决策级日志（含rule_id）
- [ ] CLI: create / confirm / revise / show / log

### Phase 1B：日更效率
- [ ] GitHub Trending / Product Hunt 热点采集
- [ ] Daily 模式（discovery_candidates.json）
- [ ] explore 命令（线索拓展）
- [ ] 完整局部重跑路由表
- [ ] Deep 模式自动触发（前后置）
- [ ] 完整日志分析指标

### Phase 2：扩展采集源与模板
- [ ] 小红书采集（cookie方式，失效降级）
- [ ] TechCrunch RSS / Twitter / 公众号
- [ ] 补齐6类模板

### Phase 3：质量增强
- [ ] 多模态模型验收图片（增加 VISUAL_REVIEW 状态，变18态）
- [ ] metrics 分析面板
- [ ] 模型按角色拆分

### Phase 4（可选）：Web 界面
- [ ] FastAPI + Streamlit

---

## 十三、配置项（.env）

```bash
# LLM Keys
DEEPSEEK_API_KEY=sk-xxx
ZHIPU_API_KEY=xxx

# 通用
LOG_LEVEL=INFO
RUNS_DIR=./runs
LOG_DIR=./logs

# 重试预算
MAX_SUPPLEMENT_RESEARCH=1        # Create模式补研
MAX_SUPPLEMENT_RESEARCH_DEEP=2   # Deep模式补研
MAX_REVISE_OUTLINE=2             # 大纲返工
MAX_REVISE_COPY=2                # 文案返工
MAX_REVISE_LAYOUT=2              # 布局返工
MAX_RENDER_RETRY=2               # 渲染重试

# 成本控制
DAILY_TOKEN_BUDGET=500000

# 安全
FETCH_ALLOWED_PROTOCOLS=http,https
FETCH_BLOCK_PRIVATE_IP=true
LOG_SENSITIVE_REDACT=true
```

---

## 十四、关键风险与应对

| 风险 | 应对 |
|---|---|
| 小红书 cookie 失效 | 失效检测+提醒+降级 |
| 小红书反爬升级 | 降级到用户手动/浏览器插件/第三方服务，不做登录态签名 |
| LLM 风格漂移 | 每次加载 style_rules 相关部分，Reviewer 自检 |
| 事实幻觉 | 证据包 + Reference Validator引用链 + Reviewer语义核验 + 来源快照 + 证据分级 |
| Researcher编造摘录 | 来源快照(snapshot_ref+content_hash) + Evidence Reviewer核对原文 |
| 图片渲染失败 | 模板预设 + Render Validator + MAX_RENDER_RETRY + HUMAN_REVIEW |
| 采集源不可用 | 多源冗余 + 采集失败降级 |
| 成本失控 | 重试预算 + 日token预算 + 日志告警 |
| 无限循环 | 6个 MAX_* 硬限制，超预算分流(FINAL/HUMAN_REVIEW/FAILED) |
| Controller 被LLM劫持 | 白名单 route_to，LLM 只给建议不决定跳转 |
| 视觉美观度不可控 | Phase 1 人工看PNG；Phase 3 多模态 |
| Prompt Injection | 网页不可信 / Fetch纯文本 / 不访问敏感信息 / URL限制防SSRF / 日志脱敏 / Jinja2自动转义 / 图标模板白名单 |
| 严重事实错误 | 可修复的走 RESEARCHING 补研；涉及机密/安全/无法恢复的严重事实问题→FAILED 终止流程，不产出可发布内容 |
| 合规风险 | 不做登录态签名破解 |

---

## 十五、验收标准

### Phase 1A 验收

**样本量**：至少10个不同主题（product_breakdown 至少5个 + trend_analysis 至少5个）。knowledge_explainer 模板放到 Phase 1B，Phase 1A 遇到不支持的内容类型时返回"当前MVP暂不支持该内容类型，请选择产品拆解或趋势解读"。

**配置项**：
```yaml
supported_content_types:
  - product_breakdown
  - trend_analysis
```

**性能指标**（系统纯处理时间，排除用户等待和第三方源不可用造成的人工暂停）：
- p50 ≤ 5 分钟
- p95 ≤ 10 分钟

**质量指标**：

| 指标 | 定义 | 推荐验收线 |
|---|---|---|
| 外部事实可追溯率 | 所有外部事实Block均有有效Claim引用链 | 100% |
| 严重事实错误 | 核心结论错误/数字错误/功能不存在/错误归因 | 0 |
| 大纲一次通过率 | 用户第一次查看后无需修改即确认 | ≥ 60% |
| 终稿可发布率 | 仅需改错别字/标签/个别措辞即可发布 | ≥ 60% |
| HTML渲染成功率 | 渲染+Render Validator通过 | ≥ 95% |
| 用户平均修改轮数 | 从首次终稿到确认完成的revise次数 | ≤ 2 轮 |

**功能验收**：
- [ ] 成功主链路15个状态可完整运行（INIT + 14业务态）；17个状态均有合法进入、退出和异常测试用例（含 HUMAN_REVIEW 恢复路由和 FAILED 终止）
- [ ] 三确认节点可交互
- [ ] topic_brief 含一句话价值 + angle_hypothesis
- [ ] evidence_pack.json 结构正确，claim含三字段+evidence_snippets+time_scope+applicability，provenance不含creator
- [ ] source 含 snapshot_ref + content_hash + accessed_at
- [ ] 证据要求分级匹配（epistemic_type+content_role）
- [ ] card_outline 含 editorial_thesis + 卡片内容意图（purpose/key_message/key_points，不含headline/body）
- [ ] draft 中每个 external_claim/mixed block 有 claim_refs，creator_opinion 已标记
- [ ] Block 条件校验通过（surface/card_id/statement_type 联动）
- [ ] 标题/封面副标题包含外部事实时有 claim_refs
- [ ] Reference Validator 通过（引用链完整 + snippet在claim中）
- [ ] Evidence Reviewer 核对来源快照（不只看Researcher提取的snippet）
- [ ] Reviewer 输出结构化结果（status/issue_type/route_to/issues带rule_id），pass时issue_type/route_to为null
- [ ] layout_spec 不含自由HTML代码
- [ ] asset_manifest 管理所有视觉素材，Renderer不直接下载URL
- [ ] 2类模板 HTML+PNG 成功渲染
- [ ] Render Validator 通过（尺寸/溢出/遮挡）
- [ ] runs/ 目录文件齐全 + artifacts/ 版本化存储 + sources/ 来源快照 + assets/ 素材
- [ ] artifacts.json 依赖图正确
- [ ] 决策级日志可查（含rule_id）
- [ ] 状态转移表全覆盖（含回退路径 + HUMAN_REVIEW + FAILED）
- [ ] 6个重试预算生效
- [ ] Prompt Injection 防护生效（Fetch只返回纯文本+来源快照、不访问敏感信息）
- [ ] 异常状态正确路由（研究/大纲阶段超预算→HUMAN_REVIEW / 文案布局阶段轻微超预算→quality_limited继续 / 严重→HUMAN_REVIEW / 不可恢复→FAILED）
- [ ] HUMAN_REVIEW 恢复路由正确（补充来源→RESEARCHING / 接受边界→OUTLINING / 修复素材→RENDERING / 接受终稿→FINAL_CONFIRMATION / 无法继续→FAILED）
- [ ] Phase 1A 素材 source 限制（user_provided/library/generated）+ available_assets→asset_manifest 流程 + local_ref 进入 RENDERING 前文件存在校验

---

## 冻结声明

本版本（v4.4）与 style_rules v2.4 共同冻结为开发基线。后续发现问题，优先通过 Pydantic Schema、状态转移单元测试和真实内容样本迭代，不再改变 Agent 数量和主状态机结构。
