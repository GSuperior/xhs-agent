# 小红书 AI 内容风格规则 v2.4

> 本文档作为 Agent 生成内容的"风格宪法"，**冻结版本**。
> v2.4 变更：统一 COPY_004 与 EVIDENCE_007（外部趋势Claim至少2个独立来源，证据不足写uncertainties不作为核心Claim；博主趋势判断走editorial_thesis，依据有限时certainty为low+非确定性表达）。
> v2.3 变更：修正"违反即失败"措辞；STYLE_011删除"硬性要求最多2行"；content_type枚举说明增加topic_subtype字段+条件校验。
> v2.2 变更：明确 HARD 与 FAILED 关系；拆分标题规则（TITLE_001 HARD + STYLE_011 SOFT）；修正趋势 Claim 与博主判断冲突；model_review 归入 comparison_review+topic_subtype；封面 card_1 固定统一编号；Phase 1A 素材 source 限制+落盘校验。
> v2.1 变更：补回各栏目正文结构蓝图；补充 VOICE/IDENTITY 规则；增加 STYLE_012 卡片字数；定义 CONTENT_007 重复阈值；拆分 angle_hypothesis/editorial_thesis；标题封面结构化；content_type 统一枚举；Source Schema 调整；增加 asset_manifest Schema；Block 条件校验。
> 配套文档：`agent_design.md` v4.4。

---

## 文档结构说明

本规则分三层，Agent 和 Reviewer 按层级判断优先级：

- **A. 硬性规则（HARD）**：当前 Artifact 不得通过审核，必须修正或进入 HUMAN_REVIEW。不代表工作流直接进入 FAILED。
- **B. 条件规则（CONDITIONAL）**：根据任务类型启用
- **C. 软性偏好（SOFT）**：可根据效果优化，Reviewer 不因软偏好未满足而判失败

> **HARD vs FAILED**：HARD 问题可返工（如术语没翻译、标题夸张、正文卡片重复、标题缺引用）。FAILED 仅用于严重事实错误、机密泄露、安全风险、无法生成有效产物等不可恢复问题。

每条规则带 ID（如 CONTENT_003），Reviewer 输出时引用 rule_id，便于日志统计"最常违反的规则"。

### content_type 公共枚举（全系统统一）

| 枚举值 | 中文展示名 |
|---|---|
| `product_breakdown` | 产品拆解 |
| `trend_analysis` | 趋势解读 |
| `knowledge_explainer` | 知识科普 |
| `hands_on_tutorial` | 实战教程 |
| `comparison_review` | 对比评测 |
| `industry_observation` | 产业观察 |

> Collector、Agent、模板、条件规则、Reviewer 全部使用同一枚举。字段格式：`{"content_type": "product_breakdown", "content_type_label": "产品拆解", "topic_subtype": null}`。topic_subtype 用于更细分类（如模型评测 `{"content_type": "comparison_review", "topic_subtype": "model_review"}`），条件校验：`if topic_subtype == "model_review": assert content_type == "comparison_review"`，其他内容可为 null。

---

## 第一部分：博主人设与受众

### 博主人设

| 项 | 内容 |
|---|---|
| 账号名 | AI产品经理GSuperior |
| 身份 | 大厂 AI 大模型产品经理 |
| 签名 | 站在产品经理视角，讲人话的 AI 内容 |
| 账号人格 | AI产品经理的一线观察和判断（非中立资讯整理，必须有观点） |
| 差异化卖点 | 大厂 AI PM 内部视角 + 产品判断 + 讲人话 |

### 受众定位（initial_hypothesis，每20-30篇按数据调整）

| 受众 | 占比 | 价值诉求 |
|---|---|---|
| 互联网职场人（PM/运营/设计师/开发） | 50% | 看懂 AI 趋势、用上 AI 工具提升效率 |
| AI 入门用户/学习者 | 30% | 建立 AI 认知，从概念到落地 |
| 求职/转行者 | 15% | 了解行业动态，建立职业判断 |
| AI 从业者 | 5% | 内部视角交叉验证 |

> Agent 生成单篇内容时只需知道主受众和栏目，不需加载精确占比。

### 栏目矩阵（initial_hypothesis，频率可调）

| 栏目 | content_type | 频率(假设) |
|---|---|---|
| 拆一个AI产品 | product_breakdown | ~40% |
| 看一个AI趋势 | trend_analysis | ~25% |
| 聊一个AI知识点 | knowledge_explainer | ~15% |
| 上一个AI实战 | hands_on_tutorial | ~15% |
| PM内部观察 | industry_observation | ~5% |

**命名公式**：`[动词]一个/一批AI[对象]：[对象原名]`

---

## 第二部分：硬性规则（HARD）

违反 HARD 规则时，当前 Artifact 不得通过审核，必须返工或进入 HUMAN_REVIEW。只有不可恢复的严重事实、安全、机密或产物问题才进入 FAILED。

### 内容硬规则

**CONTENT_001**：不编造事实。所有外部事实必须基于 evidence_pack 中的 claim。
**CONTENT_002**：不泄露内部信息。不提具体公司内部数据/未公开信息。
**CONTENT_003**：外部事实 block 必须包含有效 claim_refs（external_claim 和 mixed 类型）。
**CONTENT_004**：标题不夸大，不含未经证据支持的绝对化结论。
**CONTENT_005**：技术内容面向非技术读者，术语首次出现必须用人话解释。
**CONTENT_006**：每篇必须存在可识别的核心判断（通过 editorial_thesis 校验，不强制固定句式）。
**CONTENT_007**：正文和卡片不得大段重复。定义：逐字重复连续超过30个中文字符，或卡片文字与正文对应段落字符重合率超过70%，触发 Reviewer 检查。程序只做相似度提示，Reviewer 结合图文分工判断是否失败（产品名称、数字和核心结论的合理重复不机械判错）。
**CONTENT_008**：不自动发布到小红书（人工发布）。

### 身份硬规则

**IDENTITY_001**：不冒充全知，不知道就说不知道。
**IDENTITY_002**：评价友商产品时客观，不为黑而黑。
**IDENTITY_003**：仅在产品决策、行业观察或信任建立场景自然使用职业身份，不必每篇强调"大厂AI产品经理"。

### 语气硬规则

**VOICE_001**：优先直接、准确、通俗表达，避免无必要的专业黑话。内部视角不等于堆专业术语。
**VOICE_002**：表达判断时说明依据和不确定性。允许表达"目前信息不足以下定论"。
**VOICE_003**：不使用会制造错误认知的类比。使用类比前必须通过类比自检（见 STYLE_002）。

### 证据硬规则

**EVIDENCE_001**：claim 的 epistemic_type/content_role/provenance 枚举必须合法。provenance 不含 creator（博主观点走 editorial_thesis）。
**EVIDENCE_002**：block 的 claim_refs 必须指向存在的 claim。
**EVIDENCE_003**：claim 必须有 source_ids。source 必须有 URL、发布方、来源类型。published_at 可空（GitHub/文档类来源可能无清晰发布时间），但 accessed_at 必须存在。
**EVIDENCE_004**：claim.source_ids 中的每个 source 都必须在 claim.evidence_snippets 中有对应 source_id 的 snippet。如果某个来源只用于背景、不直接支持 claim，应放入 context_source_ids，不混入 source_ids。
**EVIDENCE_005**：creator_opinion block 不强制 claim_refs，但涉及事实依据时应填 supporting_claim_refs。
**EVIDENCE_006**：行业结论不得仅凭个人观点生成（必须有事实基础）。

### 视觉硬规则

**TITLE_001**：标题或封面文案渲染后不得超过模板允许行数（程序校验渲染后 DOM 行数）。
**VISUAL_001**：画布 1080×1440 px，安全区 72px。
**VISUAL_002**：字号以 Design Token 为唯一真源（`config/design_token.json`），全文统一 px（不混用 pt）。
**VISUAL_003**：正文最小字号 32px（1080×1440 画布下低于此不可读）。
**VISUAL_004**：DOM 不得溢出安全区，元素不得遮挡。
**VISUAL_005**：Jinja2 必须开启自动转义。
**VISUAL_006**：每张图必须有非纯文本的信息组织元素（卡片/框架/对比/图标等）。
**VISUAL_007**：视觉素材必须通过 asset_manifest 管理，Renderer 不直接下载任意 URL。

### 选题硬规则

**TOPIC_001**：选题必须能说清"一句话价值"——用户看完比只看新闻标题多知道什么。说不清不进研究。

---

## 第三部分：条件规则（CONDITIONAL）

根据 content_type 启用。

### 正文结构蓝图（按 content_type）

> 以下为推荐结构，不强制使用固定模块标题。Reviewer 检查"正文结构是否对应栏目类型"时以此为参考。

#### product_breakdown（产品拆解）
```
产品是什么
→ 核心体验或功能
→ 价值和差异
→ 限制/边界/待验证点
→ 产品视角判断
```

#### trend_analysis（趋势解读）
```
发生了什么
→ 为什么现在值得关注
→ 影响哪些用户或产品
→ 当前证据和限制
→ PM判断与置信度
```

#### knowledge_explainer（知识科普）
```
一句人话定义
→ 解决什么问题
→ 具体例子
→ 产品中如何使用
→ 常见误区
```

#### hands_on_tutorial（实战教程）
```
适用场景
→ 前置条件
→ 操作步骤
→ 结果验证
→ 适用边界
```

#### comparison_review（对比评测）
```
对比对象介绍
→ 评测维度与指标说明
→ 逐项对比结果
→ 各自优劣
→ 适用场景推荐
```

#### industry_observation（产业观察）
```
观察现象
→ 背后逻辑
→ 数据/案例支撑
→ 可能的影响
→ 个人判断与不确定性
```

### 产品拆解类条件规则

**COPY_001**：至少说明一个限制、适用边界或待验证点。没有可靠证据时写"当前公开信息还不足以判断实际效果"，不编造短板。
**COPY_002**：必须包含产品视角判断（设计逻辑/商业考量/如果是我会怎么设计）。

### 趋势解读类条件规则

**COPY_003**：需说明时间边界（这个趋势是何时开始的，目前处于什么阶段）。
**COPY_004**：外部趋势或预测性 Claim 必须满足 EVIDENCE_007，即至少有 2 个独立来源。证据不足时写入 uncertainties，不得作为正文中的核心外部 Claim。博主趋势判断应写入 editorial_thesis，通过 supporting_claim_refs 关联外部 Claim；依据有限时 certainty 应为 low，文案必须使用与置信度匹配的非确定性表达。

### 对比评测类条件规则

**COPY_005**：对比指标口径必须一致（不能 A 用月活、B 用日活）。
**COPY_006**：每个对比对象需有一手资料。

### 用户体验类条件规则

**COPY_007**：需说明样本来源，不可直接泛化（"我试了3次"不能写成"普遍体验"）。

### 知识科普类条件规则

**COPY_008**：可使用类比帮助解释陌生概念，但需满足类比自检（见 STYLE_002）。

### 严肃内容条件规则（industry_observation / comparison_review）

> 模型评测统一归入 `{"content_type": "comparison_review", "topic_subtype": "model_review"}`，Reviewer 需要更细判断时读取 topic_subtype。

**VISUAL_008**：不强制使用可爱角色，优先用框架图/时间线/矩阵/便签等专业视觉元素。

### 时效规则（按 lifecycle）

**TOPIC_002**：breaking 类选题优先 24-48 小时内发布。
**TOPIC_003**：trending 类选题 3-7 天仍有讨论价值。
**TOPIC_004**：evergreen 类选题不以时效为主要评分项。
**TOPIC_005**：series 类按栏目计划发布。

> 不对所有选题统一要求 48 小时内。

### 判断类型证据要求分级

**EVIDENCE_007**（按判断类型，非一刀切）：

| 判断类型 | 证据要求 |
|---|---|
| 纯价值偏好 | 可以无引用 |
| 产品设计建议 | 建议关联至少1条事实依据 |
| 原因解释 | 至少关联1-2条支持 Claim |
| 趋势预测 | 外部 trend/projective Claim 至少2个独立来源；证据不足时写入 uncertainties，不作为核心 Claim。博主趋势判断写入 editorial_thesis，用 certainty 标记置信度 |
| 行业结论 | 不得仅凭个人观点生成（必须有事实基础） |

> 外部 Claim 不可通过"标记为博主判断"降低证据要求。博主判断走 editorial_thesis，通过 supporting_claim_refs 关联外部 Claim。

---

## 第四部分：软性偏好（SOFT）

可根据效果优化，Reviewer 不因软偏好未满足而判失败。

### 栏目与标题

**STYLE_001**：推荐使用固定栏目前缀（拆/看/聊/上一个AI...），建系列心智。非强制。
**STYLE_002**：类比可作为解释策略之一，优先级：①一句大白话定义 ②具体产品场景/操作例子 ③确实准确时再用类比。类比自检：是否准确对应核心机制、是否比直接解释更易理解、是否可能制造错误认知。
**STYLE_003**：偶尔口语化拉近距离（每篇不超过2处）。
**STYLE_004**：海外产品可用"XX for XX"类比锚点（如"AI时代的Roblox"），非强制。

### 卡片与视觉

**STYLE_005**：默认6张卡片，允许5-8张，复杂对比/争议最多8张，少于5或超过8需理由。
**STYLE_006**：封面默认黑白极简+产品Logo点缀；内容图默认米色底+粉色高亮。accent_color 可配置。
**STYLE_007**：概念科普类内容推荐可爱角色/简笔插画；产品拆解推荐界面/Logo/流程；趋势判断推荐时间线/箭头/关系图；对比评测推荐矩阵/表格/双栏。
**STYLE_008**：反差钩子、数据佐证、提问式开头等亮点设计，按内容适用性选用。
**STYLE_012**：卡片正文推荐 40-100 字，封面主文案不超过 30 字。最终是否溢出由 Render Validator 判定。

### 标签

**STYLE_009**：标签总量5-8个。账号锚点1-2个 + 主题/对象2-3个 + 场景/人群1-2个 + 热点标签0-2个(必须相关)。`#大模型` 只在内容确实涉及大模型时使用。

### 字数

**STYLE_010**：正文默认不超过700字（为控制移动端阅读负担，实际长度可根据历史发布数据调整）。
**STYLE_011**：标题推荐12-22个中文显示宽度。系列前缀可单独显示，不计入主标题。英文产品名不得为压缩长度而翻译或截断。标题渲染行数由 TITLE_001 进行硬性校验。

---

## 第五部分：Schema 定义

### Claim 结构（evidence_pack.json）

研究取证 Agent 只生成外部 claim，**不生成 creator 观点**（provenance 不含 creator）。

```json
{
  "claim_id": "c1",
  "claim": "",
  "epistemic_type": "factual|interpretive|projective|experiential",
  "content_role": "core|background|comparison|limitation|case|trend",
  "provenance": "official|media|community|user",
  "source_ids": ["s1"],
  "context_source_ids": [],
  "evidence_snippets": [
    {
      "source_id": "s1",
      "snippet": "原文短摘录",
      "location": "Release Notes / Section 2"
    }
  ],
  "confidence": "high|medium|low",
  "confidence_reason": "",
  "time_scope": "截至2026-07-13",
  "applicability": "仅适用于Pro版本"
}
```

> - provenance 不含 creator。博主观点走 editorial_thesis。
> - source_ids 中的每个 source 都必须有对应 evidence_snippet。
> - 只用于背景的来源放 context_source_ids，不要求 snippet。

### Source 结构

```json
{
  "source_id": "s1",
  "publisher": "",
  "url": "",
  "published_at": null,
  "updated_at": null,
  "accessed_at": "2026-07-14T10:20:00",
  "version_or_commit": null,
  "source_type": "primary|media|user|community",
  "snapshot_ref": "sources/s1.txt",
  "content_hash": "sha256:..."
}
```

> - source 不含 snippet。snippet 在 claim.evidence_snippets 中。
> - published_at 可空（GitHub/文档类可能无清晰发布时间）；accessed_at 必须存在。
> - GitHub 或文档类来源优先记录 version_or_commit / updated_at。
> - snapshot_ref + content_hash 用于 Evidence Reviewer 核对来源原文（防 Researcher 编造摘录）。

### 引用链（正确顺序）

```
block.claim_refs / supporting_claim_refs
→ claim 存在
→ claim.source_ids 非空
→ source_ids 对应的 source 存在
→ claim.evidence_snippets 中存在对应 source_id 的 snippet
```

### Block 结构（draft.json）

```json
{
  "block_id": "b1",
  "surface": "body|card",
  "card_id": null,
  "text": "",
  "statement_type": "external_claim|creator_opinion|mixed",
  "claim_refs": ["c1"],
  "supporting_claim_refs": []
}
```

**条件校验**：

| 条件 | 规则 |
|---|---|
| `surface=body` | `card_id` 必须为 null |
| `surface=card` | `card_id` 必须存在 |
| `statement_type=external_claim` | `claim_refs` 不能为空 |
| `statement_type=mixed` | `claim_refs` 不能为空 |
| `statement_type=creator_opinion` | `claim_refs` 可空，有事实依据时填 `supporting_claim_refs` |

### Angle Hypothesis（研究前，在 topic_brief.json）

选题角度确认发生在研究之前，此时还没有 Claim ID，无法填 supporting_claim_refs。用 angle_hypothesis 表达待验证的内容角度。

```json
{
  "angle_hypothesis": {
    "statement": "这次更新的主要价值可能是降低AI工具使用门槛",
    "questions_to_verify": [
      "是否真的降低了操作步骤",
      "是否只面向付费用户"
    ]
  }
}
```

> 它是待验证的内容角度，不作为最终结论。避免研究结果与前置判断不一致时 Agent 强行寻找支持材料。

### Editorial Thesis（研究后，在 card_outline.json）

由内容规划 Agent 根据 Evidence 生成，用户在 OUTLINE_CONFIRMATION 确认最终判断。

```json
{
  "editorial_thesis": {
    "statement": "我认为这次更新真正降低的是首次使用门槛，但没有显著降低专业使用成本。",
    "supporting_claim_refs": ["c2", "c5"],
    "certainty": "high|medium|low"
  }
}
```

> 研究事实与博主判断边界清楚：evidence_pack 只装外部 claim，editorial_thesis 装博主判断。

### 卡片大纲结构（card_outline.json，内容规划 Agent 输出）

内容规划 Agent 只输出**内容意图**，不写具体文案（headline/body 由文案 Agent 生成）。card_1 封面也包含在 cards 数组中：

```json
{
  "editorial_thesis": { ... },
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

> thesis_ref 只能为 "editorial_thesis" 或 null。内容规划 Agent 负责"讲什么"，文案 Agent 负责"具体怎么表达"。

### 标题与封面结构（带引用约束）

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
  }
}
```

> 标题和封面副标题如果包含外部事实（如数字、结论），必须有 claim_refs，否则成为事实约束的漏洞。

### 卡片路径（按 content_role + epistemic_type 筛选）

> card_1 固定为封面，card_2~card_6 为内容页。card_outline 和 draft 的 cover 都引用 card_id="card_1"。

| 卡片 | 主要 content_role | 允许的 epistemic_type |
|---|---|---|
| card_1（封面） | core | factual/interpretive/projective |
| card_2 发生了什么 | core/background | factual |
| card_3 为什么值得关注 | core/background/trend | factual/interpretive |
| card_4 核心机制 | core/comparison | factual/interpretive |
| card_5 用户场景 | case | factual/experiential |
| card_6 PM判断 | core/trend | interpretive/projective |
| card_7（可选）局限争议 | limitation | factual/interpretive/experiential |
| card_8（可选）总结建议 | core | interpretive/projective |

> card_6 PM判断的主要内容是 editorial_thesis（thesis_ref="editorial_thesis"），支持依据是 supporting_claim_refs。thesis_ref 只能为 "editorial_thesis" 或 null。

### 视觉素材清单（asset_manifest.json）

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

> 视觉规划 Agent 只引用 asset_id，Renderer 不直接下载任意 URL。控制素材缺失、加载失败、不可信 URL、品牌 Logo 版本、版权边界。
> **Phase 1A 限制**：asset.source 只能为 user_provided / library / generated（不含 official 远程下载）。素材落盘时间顺序：用户上传/素材库准备素材→生成 available_assets.json→VISUAL_PLANNING 从中选择生成 asset_manifest.json→进入 RENDERING 前检查所有 local_ref 是否存在。official 远程素材下载和 Asset Resolver 放入 Phase 1B。

### Design Token（视觉唯一真源，config/design_token.json）

```json
{
  "canvas": "1080x1440",
  "safe_area": 72,
  "font_scale": {
    "cover_main": 76,
    "cover_subtitle": 34,
    "card_heading": 48,
    "card_body": 32,
    "caption": 24,
    "badge": 26
  },
  "line_height": {
    "heading": 1.25,
    "body": 1.55
  },
  "cover_theme": {
    "background": "#FFFFFF",
    "foreground": "#000000",
    "accent_source": "brand"
  },
  "content_theme": {
    "background": "#F5F0E8",
    "foreground": "#333333",
    "accent": "#FF6B8A"
  }
}
```

> accent 可配置。agent_design.md 不保留 Design Token 副本，以此处为唯一真源。

---

## 第六部分：选题评分与 lifecycle

### 评分权重

| 指标 | 权重 |
|---|---:|
| 对非技术用户的价值 | 25% |
| 产品视角可分析性 | 20% |
| 时效性 | 15% |
| 信息增量 | 15% |
| 标题和视觉表达潜力 | 15% |
| 证据可靠性 | 10% |

### lifecycle 分类（替代固定 expiry）

```json
{
  "lifecycle": "breaking|trending|evergreen|series",
  "valid_until": "2026-07-16",
  "refresh_required": true
}
```

- breaking：24-48小时
- trending：3-7天
- evergreen：长期有效
- series：栏目型内容

---

## 第七部分：禁忌清单

### 内容禁忌
- ❌ 编造事实/无来源数字
- ❌ 只描述不评价（没有观点=没有价值）
- ❌ 标题党（失信于用户）
- ❌ 一味吹捧（不写限制/边界=不客观，但无证据时不编造短板）
- ❌ 翻译产品名（用原名）
- ❌ 脱离产品视角讲技术实现
- ❌ 行业结论仅凭个人观点

### 身份禁忌
- ❌ 每篇强行塞"大厂AI产品经理"身份
- ❌ 提具体公司内部数据/未公开信息
- ❌ 为黑而黑踩竞品
- ❌ 冒充全知
- ❌ 堆专业黑话代替通俗解释

### 视觉禁忌
- ❌ 配色超过 3 种主色
- ❌ 字号低于 32px（1080×1440 画布）
- ❌ pt/px 混用（全文统一 px）
- ❌ 纯文字图（必须有信息组织元素）
- ❌ 严肃内容强制可爱角色
- ❌ Renderer 直接下载任意 URL（必须通过 asset_manifest）

---

## 第八部分：Reviewer 自检清单

### 内容自检
- [ ] 标题是否符合 STYLE_011（显示宽度/行数）？不夸大（CONTENT_004）？
- [ ] 正文结构是否对应栏目类型（见第三部分正文结构蓝图）？
- [ ] 是否存在可识别的核心判断（CONTENT_006，通过 editorial_thesis 校验，不搜"我认为"）？
- [ ] 技术术语是否都已翻译（CONTENT_005）？
- [ ] 是否说明限制/适用边界/待验证点（COPY_001，产品拆解类）？
- [ ] 字数是否合理（STYLE_010，默认≤700字）？
- [ ] 标签是否 5-8 个（STYLE_009）？
- [ ] 账号人格是否体现"一线观察判断"？
- [ ] 正文和卡片是否大段重复（CONTENT_007，逐字>30字或重合率>70%触发检查）？

### 卡片自检
- [ ] 默认6张，5-8范围（STYLE_005）？
- [ ] 每张卡片文字 40-100 字，封面≤30字（STYLE_012）？
- [ ] 每张卡片是否只讲一个中心信息？
- [ ] 卡片 claim_refs 是否都在 evidence_pack 中（EVIDENCE_002）？
- [ ] 卡片文字与正文是否重复（CONTENT_007）？
- [ ] 图文分工是否合理？

### 视觉自检
- [ ] 画布 1080×1440，安全区72px（VISUAL_001）？
- [ ] 字号是否符合 Design Token（VISUAL_002，全文px）？
- [ ] DOM 是否溢出/遮挡（VISUAL_004）？
- [ ] 每张图是否有非纯文本信息组织元素（VISUAL_006）？
- [ ] 素材是否通过 asset_manifest 管理（VISUAL_007）？

### 证据自检（程序校验 + Reviewer语义核验）
- [ ] claim 的 epistemic_type/content_role/provenance 枚举合法（EVIDENCE_001）？provenance 不含 creator？
- [ ] block 的 claim_refs/supporting_claim_refs 是否都存在（EVIDENCE_002）？
- [ ] claim 是否有 source_ids（EVIDENCE_003）？
- [ ] source 是否有 URL/发布方/来源类型？accessed_at 是否存在（EVIDENCE_003）？
- [ ] claim.source_ids 中每个 source 是否有对应 evidence_snippet（EVIDENCE_004，snippet在claim中不在source中）？背景来源是否放 context_source_ids？
- [ ] 每个外部事实（external_claim/mixed block）是否有 claim_refs（CONTENT_003）？
- [ ] 标题/封面副标题包含外部事实时是否有 claim_refs？
- [ ] creator_opinion 是否已标记，涉及事实依据时填 supporting_claim_refs（EVIDENCE_005）？
- [ ] Block 条件校验：surface=body→card_id=null？surface=card→card_id存在？external_claim/mixed→claim_refs非空？
- [ ] 判断类型证据要求是否分级满足（EVIDENCE_007）？
- [ ] （Reviewer语义+来源快照）claim 是否被来源真正支持？Snippet 是否断章取义？是否有未引用事实？

---

## 第九部分：按角色加载规则

各 Agent 只加载相关规则，减少上下文长度和无关规则干扰：

| Agent | 加载内容 |
|---|---|
| 选题发现与策划Agent | 人设、受众、栏目、选题策略、lifecycle、评分权重、angle_hypothesis |
| 研究取证Agent | 证据规则(EVIDENCE_*)、时效规则(TOPIC_002~005)、身份边界(IDENTITY_*)、Claim Schema、Source Schema |
| 内容规划Agent | 正文结构蓝图、卡片路径(content_role+epistemic_type)、图文分工、editorial_thesis、card_outline Schema |
| 文案Agent | 标题规则(STYLE_011)、语气(VOICE_*/STYLE_003/004)、正文(STYLE_010)、标签(STYLE_009)、禁忌、Block Schema、标题封面结构 |
| 视觉规划Agent | 封面/内容图规范、Design Token、STYLE_005/006/007/012、VISUAL_*、asset_manifest |
| Reviewer | 当前阶段全部相关规则 + 规则ID（输出时引用 rule_id） |

---

## 第十部分：对第五轮设计师建议的取舍说明

### 完全采纳（19条全部采纳）

**P0必须修正**：
- ✅ 状态数修正（见 agent_design v4.1，INIT+14业务态+HUMAN_REVIEW+FAILED=17态）
- ✅ 从 agent_design 删除 creator provenance，卡片6改为 editorial_thesis+supporting_claim_refs
- ✅ 拆分 angle_hypothesis（研究前，topic_brief）和 editorial_thesis（研究后，card_outline）
- ✅ 内容规划 Agent 只输出内容意图（purpose/key_message/key_points），文案 Agent 负责表达
- ✅ Block Schema 加 supporting_claim_refs + 条件校验（surface/card_id/statement_type 联动）
- ✅ 标题和封面文字结构化（带 claim_refs/supporting_claim_refs）
- ✅ 修正引用链描述（snippet 在 claim.evidence_snippets，source_ids 每个 source 必须有 snippet，背景来源放 context_source_ids）
- ✅ Source 增加快照（snapshot_ref/content_hash），Evidence Reviewer 核对来源原文
- ✅ Reviewer 结果 pass 时 issue_type/route_to 为 null，blocked 进 human_review，每个 issue 带 rule_id
- ✅ 增加 HUMAN_REVIEW 和 FAILED 状态（见 agent_design v4.1）

**公共枚举统一**：
- ✅ content_type 统一枚举（product_breakdown/trend_analysis/knowledge_explainer/hands_on_tutorial/comparison_review/industry_observation）+ content_type_label
- ✅ Design Token 以 style_rules 为唯一真源，agent_design 删除副本

**style_rules 缺失内容**：
- ✅ 补回各栏目正文结构蓝图（CONDITIONAL）
- ✅ 补充 IDENTITY_003 / VOICE_001 / VOICE_002 / VOICE_003
- ✅ 增加 STYLE_012（卡片字数）
- ✅ 定义 CONTENT_007"大段重复"阈值（逐字>30字或重合率>70%）

**工程验收补充**：
- ✅ Source Schema 调整（published_at 可空，accessed_at 必填，加 updated_at/version_or_commit）
- ✅ 增加 asset_manifest.json（视觉素材清单）
- ✅ 验收指标补充样本量（见 agent_design v4.1）

### 不采纳
- 无。这轮反馈全部命中跨文档口径冲突或 Schema 不一致。

---

## 第十一部分：对第六轮设计师建议的取舍说明

### 完全采纳（7项全部采纳）

1. ✅ 补全 HUMAN_REVIEW 恢复路径 + 状态数据 + 恢复路由（见 agent_design v4.2 第三节）
2. ✅ 修正趋势 Claim 与博主判断冲突（外部 trend 至少2源 / 博主判断走 editorial_thesis，外部 Claim 不可标记为博主判断降低证据要求）
3. ✅ model_review 归入 comparison_review + topic_subtype（VISUAL_008 适用范围修正）
4. ✅ 明确 HARD 与 FAILED 关系（HARD=不得通过审核需修正 / FAILED=不可恢复），拆分标题规则（TITLE_001 HARD 渲染行数 + STYLE_011 SOFT 显示宽度）
5. ✅ Phase 1A 验收改为 2 类各 5 个样本（product_breakdown + trend_analysis），knowledge_explainer 放 Phase 1B
6. ✅ 封面 card_1 固定统一编号（card_outline + draft cover + 卡片路径表一致）
7. ✅ Phase 1A 素材 source 限制（user_provided/library/generated）+ local_ref 文件存在校验

### 延后（设计师明确建议延后，不影响 Phase 1A 启动）
- editorial_copy（先让无事实主张文字用 creator_opinion）
- 完整 Asset Resolver（Phase 1B）
- 补齐所有 Reviewer 规则 ID（发现高频问题后再增加）
- Prompt Injection 检测 Agent（现有权限隔离和 URL 限制先落地）
- Agent 数量和主流程调整（不再改变）

### 不采纳
- 无。

---

## 第十二部分：对第七轮设计师建议的取舍说明

### 完全采纳（5项+1项增强全部采纳）

1. ✅ 修正 Controller 图超预算路由（与详细转移表一致，见 agent_design v4.3 第二节架构图）
2. ✅ 修正"违反即失败"措辞（改为不得通过审核需返工，只有不可恢复问题进 FAILED）
3. ✅ 彻底拆开 TITLE_001（HARD 渲染行数）与 STYLE_011（SOFT 显示宽度，删除"硬性要求最多2行"）
4. ✅ Schema 增加 topic_subtype 字段（discovery_candidates/selected_topic/topic_brief + 条件校验 `if topic_subtype == "model_review": assert content_type == "comparison_review"`）
5. ✅ 修正素材落盘时间顺序（available_assets→asset_manifest→RENDERING前校验，取代"VISUAL_PLANNING前存在"）
6. ✅ HUMAN_REVIEW 状态数据改为 action_routes 映射（替代 resume_state+available_actions，见 agent_design v4.3）

### 不采纳
- 无。

---

## 第十三部分：对第八轮设计师建议的取舍说明

### 完全采纳（4项全部采纳）

1. ✅ 补完整 FAILED 数据链路（Reviewer Schema 加 failed 状态 + issue_type 加 safety + route_to 加 failed，仅用于不可恢复问题）+ 限定状态转移表触发条件（"严重事实错误→FAILED"改为"涉及机密/安全/无法恢复的严重事实问题→FAILED"，可修复事实错误走 RESEARCHING 补研）（见 agent_design v4.4）
2. ✅ 统一 COPY_004 与 EVIDENCE_007（外部趋势Claim至少2个独立来源，证据不足写uncertainties不作为核心Claim；博主趋势判断走editorial_thesis，依据有限时certainty为low+非确定性表达）
3. ✅ 明确 card_6 三字段语义（claim_refs=卡片直接陈述的外部事实，可空；thesis_ref=是否承载editorial_thesis；editorial_thesis.supporting_claim_refs=支撑博主判断的外部Claim）（见 agent_design v4.4 图文分工约束）
4. ✅ Reference Validator 扩大覆盖范围（12类引用点全检：evidence_pack.source_ids/context_source_ids/snippets + card_outline.editorial_thesis/cards.claim_refs/thesis_ref + draft.blocks/titles/cover 全字段）+ 流程门禁（OUTLINING和DRAFTING后必检）（见 agent_design v4.4）

### 不采纳（设计师明确建议延后）
- 不给 card_outline 每张卡片新增 supporting_claim_refs（现有结构可成立）
- 不增加 editorial_copy
- 不现在补齐所有 Reviewer 规则 ID
- 不扩充 Layout Review 输入说明
- 不增加新 Agent 或新状态
- 不开发完整 Asset Resolver
- 不再更换主架构

### 不采纳
- 无。

---

## 冻结声明

本版本（v2.4）与 agent_design v4.4 共同冻结为开发基线。后续发现问题，优先通过 Pydantic Schema、状态转移单元测试和真实内容样本迭代，不再改变 Agent 数量和主状态机结构。
