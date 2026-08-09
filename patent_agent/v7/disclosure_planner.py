"""V7 Patent Disclosure Planner - native Chinese disclosure generation.

Architecture (V7):

    Evidence (any language)
      -> fact clustering (deterministic technical chain)
      -> full 9-section disclosure plan
      -> per-section Chinese generation (LLM restructures, never sentence-
         by-sentence translation; symbols/formulas preserved)
      -> GroundedDisclosure with per-paragraph fact/evidence ids

Facts are grounding INPUT, never disclosure paragraphs (fact != paragraph).
The 技术方案 detailed section is organized as a technical chain of dynamic
subsections derived from fact clustering - not a fact dump.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from patent_agent.core.models import (
    EvidenceStatus,
    GroundedDisclosure,
    GroundedParagraph,
    GroundedSection,
    ReviewStatus,
)
from patent_agent.v7.language_gate import _clean_html

CJK = re.compile(r"[一-鿿]")
FORMULA_PREFIX = re.compile(r"^(FORMULA|SYMBOL|PARAM)\s+", re.MULTILINE)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "with", "from", "by", "to",
    "in", "on", "is", "are", "be", "as", "at", "that", "this", "these",
    "those", "its", "each", "all", "only", "using", "used", "use", "then",
    "via", "which", "based", "includes", "also", "can", "may", "into", "over",
    "between", "through", "after", "before", "during", "such", "than", "not",
    "no", "was", "were", "been", "has", "have", "had", "it", "their", "there",
}

CN_NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

# Phase lexicon for embodiment grouping (generic, not case-specific).
PHASE_LEXICON: list[tuple[str, list[str]]] = [
    ("数据构建", ["dataset", "data", "sample", "parameterised", "parameterized",
                  "latin hypercube", "generated", "split", "数据集", "采样", "拉丁超立方"]),
    ("生成模型训练", ["train", "training", "epoch", "loss", "optimizer", "latent",
                    "encoder", "decoder", "posterior", "pretrain", "预训练", "训练",
                    "损失", "编码器", "解码器", "潜在"]),
    ("代理模型构建", ["surrogate", "predict", "regression", "modulation", "filim",
                    "feature-wise", "代理", "预测", "回归", "调制"]),
    ("优化设计", ["optimiz", "current vector", "nsga", "objective", "constraint",
                 "pareto", "voltage", "转矩", "电流矢量", "多目标", "约束", "优化"]),
    ("验证与筛选", ["fea", "verify", "screen", "validation", "test", "magnetostatic",
                  "有限元", "验证", "筛选", "测试", "静磁场"]),
]

CHINESE_STYLE_RULES = """
## 中文专利交底书撰写规则（严格遵守）

### 语言
1. 全部使用简体中文。禁止输出英文段落。
2. 技术术语首次出现：中文全称（English Full Name，缩写），例如：
   流匹配（Flow Matching，FM）；后续统一用中文或缩写。
3. 数学符号、公式、拉丁缩写、型号、材料牌号、单位必须原样保留，一字不改。
   只翻译自然语言；方程内的文字（min、E、D_KL、N(0,I) 等）保持原样。

### 专利表达
4. 使用"本技术方案""本发明""所述"等专利书面语。
5. 禁止学术论文口吻：本文提出、本研究表明、我们设计、实验表明（可用
   "测试结果表明"）。
6. 禁止宣传用语：极大、革命性、显著优于、行业领先。

### 事实约束
7. 每个技术陈述必须基于提供的参考材料；不编造材料中不存在的参数、数据、
   模块、步骤或公式。材料缺失的信息标注"待发明人补充"。
8. 不得引入与参考材料无关的技术内容。

### 结构
9. 只输出正文段落，不要输出章节标题（标题由系统添加）。
10. 每段一个技术主题，段落间用空行分隔。
"""


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]{2,}", text.lower()) if t not in STOPWORDS}


def cluster_facts(facts, threshold: float = 0.30) -> list[list]:
    """Deterministic technical-chain clustering of facts.

    Order-preserving greedy clustering by token overlap. Each cluster becomes
    one subsection of 技术方案详细说明 (5.N) - the technical chain.
    """
    clusters: list[tuple[set[str], list]] = []
    for fact in facts:
        if getattr(fact, "review_status", None) == ReviewStatus.REJECTED:
            continue
        toks = _tokens(str(getattr(fact, "statement", "")))
        best = None
        best_score = 0.0
        for cl in clusters:
            if not cl[0]:
                continue
            score = len(toks & cl[0]) / max(1, min(len(toks), len(cl[0])))
            if score > best_score:
                best, best_score = cl, score
        if best is not None and best_score >= threshold:
            best[0] |= toks
            best[1].append(fact)
        else:
            clusters.append([toks, [fact]])
    return [facts for _, facts in clusters]


def _phase_of(facts: list) -> str:
    """Assign an embodiment phase label to a fact cluster by lexicon hits."""
    text = " ".join(str(getattr(f, "statement", "")) for f in facts).lower()
    best_phase, best_hits = None, 0
    for label, kws in PHASE_LEXICON:
        hits = sum(1 for kw in kws if kw.lower() in text)
        if hits > best_hits:
            best_phase, best_hits = label, hits
    return best_phase or "实施细节"


def _clean_statement(fact) -> str:
    text = FORMULA_PREFIX.sub("", str(getattr(fact, "statement", ""))).strip()
    return text


def _text_retry(provider, system_prompt: str, user_prompt: str, attempts: int = 3,
                cache_dir=None) -> str:
    """Retry a direct generate_text call with short backoff, case-locally
    cached so a restart after a gate failure replays C instantly.

    Direct planner calls bypass StructuredLLMService (no schema, no service
    retry), so connection-level failures (timeouts, HTTP errors) are retried
    here with backoff - otherwise one slow/stalled provider call would crash
    the whole disclosure stage.
    """
    cache_path = None
    if cache_dir is not None:
        key = hashlib.sha256((system_prompt + "\x00" + user_prompt).encode("utf-8")).hexdigest()
        cache_path = Path(cache_dir) / f"planner_{key}.json"
        try:
            if cache_path.exists():
                return str(json.loads(cache_path.read_text(encoding="utf-8"))["text"])
        except (OSError, ValueError, KeyError):
            cache_path.unlink(missing_ok=True)
    last = None
    for attempt in range(attempts):
        try:
            raw = provider.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
            text = getattr(raw, "text", str(raw))
            if cache_path is not None:
                try:
                    cache_path.write_text(json.dumps({"text": text}, ensure_ascii=False),
                                          encoding="utf-8")
                except OSError:
                    pass
            return text
        except Exception as exc:  # connection/schema failures are retryable
            last = exc
            if attempt < attempts - 1:
                time.sleep(min(5 * (2 ** attempt), 20))
    raise last


class PatentDisclosurePlanner:
    """Generate a complete Chinese disclosure directly from understanding."""

    def __init__(self, provider=None, max_title_cjk: int = 25, cache_dir=None):
        self.provider = provider
        self.max_title_cjk = max_title_cjk
        self.cache_dir = cache_dir
        self.term_normalizer = None

    # ── title ────────────────────────────────────────────────────────────
    def generate_title(self, understanding, strategy) -> str:
        """Generate a concise Chinese patent title (<= max_title_cjk CJK)."""
        invent = str(getattr(strategy, "inventive_concept", ""))[:400]
        field = "；".join(
            str(getattr(s, "text", ""))[:120] for s in
            (getattr(understanding, "technical_field", []) or [])[:3]
        )[:400]
        facts = " ".join(
            _clean_statement(f) for f in (getattr(understanding, "facts", []) or [])[:8]
        )[:800]
        for attempt in range(2):
            prompt = (
                "请为以下技术方案生成一个简洁、技术准确的中文发明专利名称。\n"
                f"核心构思：{invent}\n"
                f"技术领域：{field}\n"
                f"技术事实：{facts}\n\n"
                "要求：\n"
                f"1. 简体中文；字数不超过 {self.max_title_cjk} 个汉字；\n"
                "2. 不含标点、不含英文缩写、不含'一种基于'以外的多余前缀；\n"
                "3. 仅输出 JSON：{\"title\": \"...\"}"
            )
            text = _text_retry(self.provider, system_prompt=CHINESE_STYLE_RULES,
                               user_prompt=prompt, cache_dir=self.cache_dir)
            match = re.search(r'"title"\s*:\s*"([^"]+)"', text)
            title = match.group(1) if match else text.strip().strip("{}").strip()
            title = title.strip().strip('"').strip()
            if title and len(CJK.findall(title)) <= self.max_title_cjk:
                return title
        raise ValueError(
            f"TITLE_GATE_FAILED: 系统生成的发明名称非中文或超长: {title!r}"
        )

    def generate_section_titles(self, clusters: list[list]) -> list[str]:
        """Plan concise semantic titles independently from section prose."""
        from patent_agent.v7_1.quality import HeadingCompletenessValidator

        items = []
        for index, cluster in enumerate(clusters, 1):
            statements = [_clean_statement(f) for f in cluster[:8]]
            items.append({"index": index, "facts": statements})
        prompt = (
            "V7.1_SECTION_TITLE_SCHEMA\n"
            "请仅依据每组技术事实，为专利技术方案的各个环节规划一个独立、完整、简洁的中文名词性标题。\n"
            "标题不是正文摘要，不得从正文截取，不得以‘本环节’‘本步骤’开头，不得以连词或助词结尾。\n"
            "不得添加材料未支持的技术内容。不要包含5.x编号。\n"
            f"事实组：{json.dumps(items, ensure_ascii=False)}\n"
            "仅输出JSON对象：{\"titles\":[\"标题一\",\"标题二\"]}"
        )
        last_titles: list[str] = []
        for _ in range(2):
            text = _text_retry(self.provider, system_prompt=CHINESE_STYLE_RULES,
                               user_prompt=prompt, cache_dir=self.cache_dir)
            match = re.search(r"\{.*\}", text, re.S)
            try:
                data = json.loads(match.group(0) if match else text)
                last_titles = [str(item).strip() for item in data.get("titles", [])]
            except (json.JSONDecodeError, AttributeError, TypeError):
                last_titles = []
            if len(last_titles) != len(clusters):
                continue
            result = HeadingCompletenessValidator().validate(last_titles)
            if result.status == "PASS" and all(2 <= len(title) <= 36 for title in last_titles):
                return last_titles
        raise ValueError(f"SECTION_TITLE_GATE_FAILED: {last_titles!r}")

    # ── content plan ─────────────────────────────────────────────────────
    def build_plan(
        self, understanding, strategy, figures, clusters, title: str = "",
        section_titles: list[str] | None = None,
    ) -> list[dict]:
        """Build the full 9-section disclosure plan.

        Returns a list of section dicts:
        {section_id, title, kind, facts, evidence_ids, plan_extra}
        kind: title|field|background|invention|solution_parent|solution|
              figures|embodiments|agency|questions

        The 9 semantic sections are always present (disclosure schema):
        1. 发明名称 / 2. 技术领域 / 3. 背景技术 / 4. 发明内容 /
        5. 技术方案详细说明 (with 5.N dynamic subsections) / 6. 附图说明 /
        7. 具体实施方式 (实施例 per phase) / 8. 代理机构说明 / 9. 待确认信息.
        """
        ev_ids = lambda objs: sorted({e for o in objs for e in (getattr(o, "evidence_ids", []) or [])})
        facts_all = [f for f in (getattr(understanding, "facts", []) or [])
                     if getattr(f, "review_status", None) != ReviewStatus.REJECTED]
        all_evidence = ev_ids(facts_all)

        plan: list[dict] = [
            {
                "section_id": "01", "title": "1. 发明名称", "kind": "title",
                "facts": [], "evidence_ids": all_evidence,
                "title_text": title or "（发明名称待确认）",
            },
            {
                "section_id": "02", "title": "2. 技术领域", "kind": "field",
                "facts": [], "evidence_ids": ev_ids(getattr(understanding, "technical_field", []) or []),
            },
            {
                "section_id": "03", "title": "3. 背景技术", "kind": "background",
                "facts": [], "evidence_ids": ev_ids((getattr(understanding, "technical_problems", []) or [])) or all_evidence,
            },
            {
                "section_id": "04", "title": "4. 发明内容", "kind": "invention",
                "facts": [], "evidence_ids": all_evidence,
            },
        ]

        # 技术方案详细说明: parent wrapper + one subsection per technical-
        # chain cluster (5.1..5.N) - the disclosure schema requires the
        # "技术方案" semantic section to exist as a heading.
        plan.append({
            "section_id": "05", "title": "5. 技术方案详细说明",
            "kind": "solution_parent",
            "facts": facts_all,
            "evidence_ids": all_evidence,
        })
        for index, cluster in enumerate(clusters, 1):
            semantic_title = (
                section_titles[index - 1]
                if section_titles is not None and index <= len(section_titles)
                else f"技术环节{index}"
            )
            plan.append({
                "section_id": f"05-{index:02d}",
                "title": f"5.{index} {semantic_title}",
                "kind": "solution",
                "facts": cluster,
                "evidence_ids": ev_ids(cluster),
            })

        plan.append({
            "section_id": "06", "title": "6. 附图说明", "kind": "figures",
            "facts": [], "evidence_ids": all_evidence,
            "figures": figures,
        })

        # 具体实施方式: embodiments grouped by phase
        phase_groups: dict[str, list] = {}
        for cluster in clusters:
            phase_groups.setdefault(_phase_of(cluster), []).append(cluster)
        for index, (phase, groups) in enumerate(phase_groups.items(), 1):
            group_facts = [f for g in groups for f in g]
            plan.append({
                "section_id": f"07-{index:02d}", "title": "", "kind": "embodiment",
                "facts": group_facts, "evidence_ids": ev_ids(group_facts),
                "phase": phase,
            })

        plan.append({
            "section_id": "08", "title": "8. 建议重点向专利代理机构说明的技术内容",
            "kind": "agency", "facts": [],
            "evidence_ids": ev_ids(getattr(strategy, "independent_claim_core", []) or []),
        })

        plan.append({
            "section_id": "09", "title": "9. 待发明人或代理机构进一步确认的信息",
            "kind": "questions", "facts": [],
            "evidence_ids": ev_ids(getattr(understanding, "uncertainties", []) or []),
        })
        return plan

    # ── generation ───────────────────────────────────────────────────────
    def plan(self, case_id: str, understanding, evidence_store, strategy,
             figures, provider=None) -> GroundedDisclosure:
        """Full native-Chinese disclosure generation."""
        if provider is not None:
            self.provider = provider
        if self.provider is None:
            raise RuntimeError("V7_DISCLOSURE_LLM_REQUIRED: Chinese generation needs an LLM provider")

        title = self.generate_title(understanding, strategy)
        facts_all = [f for f in (getattr(understanding, "facts", []) or [])
                     if getattr(f, "review_status", None) != ReviewStatus.REJECTED]
        clusters = cluster_facts(facts_all)
        source_texts = [_clean_statement(f) for f in facts_all]
        if evidence_store is not None:
            source_texts.extend(
                str(getattr(chunk, "raw_text", "") or getattr(chunk, "normalized_text", ""))
                for chunk in evidence_store.all()
            )
        from patent_agent.v7_1.quality import TechnicalTerminologyNormalizer
        self.term_normalizer = TechnicalTerminologyNormalizer.from_source_texts(source_texts)
        section_titles = self.generate_section_titles(clusters)
        plan = self.build_plan(
            understanding, strategy, figures, clusters, title=title,
            section_titles=section_titles,
        )

        sections: list[GroundedSection] = []
        for sec in plan:
            section = self._generate_section(case_id, sec, understanding, evidence_store, strategy)
            sections.append(section)

        return GroundedDisclosure(title=title, sections=sections)

    def _evidence_excerpts(self, evidence_store, evidence_ids, limit: int = 5,
                           max_chars: int = 2500) -> str:
        """Raw evidence excerpts (source language preserved) for LLM context."""
        chunks = evidence_store.all() if evidence_store is not None else []
        by_id = {getattr(c, "evidence_id", ""): c for c in chunks}
        out: list[str] = []
        total = 0
        for eid in evidence_ids:
            chunk = by_id.get(eid)
            if chunk is None:
                continue
            text = str(getattr(chunk, "raw_text", "") or getattr(chunk, "normalized_text", ""))
            if not text:
                continue
            text = re.sub(r"Fig\.\s*\d+[\.\s]*", "", text)[:600]
            if len(text) < 30:
                continue
            out.append(f"[{eid}] {text}")
            total += len(text)
            if len(out) >= limit or total > max_chars:
                break
        return "\n".join(out)

    def _facts_text(self, facts, limit: int = 10) -> str:
        return "\n".join(
            f"- {_clean_statement(f)}" for f in facts[:limit]
        )

    def _llm_paragraphs(self, purpose: str, context: str, estimated: int) -> list[str]:
        """One LLM call -> Chinese paragraphs (blank-line separated)."""
        prompt = (
            f"请撰写以下专利技术交底书章节的中文正文：\n\n"
            f"章节目的：{purpose}\n"
            f"建议段落数：{estimated}（根据材料信息量可调整）\n\n"
            f"### 参考技术材料（可能为英文，请用准确中文专利技术语言重新组织，"
            f"不是逐句翻译）\n{context}\n\n"
            "### 输出\n输出纯中文正文段落，每段之间用空行分隔。不要输出章节标题。"
        )
        text = _text_retry(self.provider, system_prompt=CHINESE_STYLE_RULES,
                           user_prompt=prompt, cache_dir=self.cache_dir)
        paragraphs = [
            p.strip() for p in re.split(r"\n\s*\n", text)
            if p.strip() and len(p.strip()) > 12 and not p.strip().startswith(("#", "```"))
        ]
        if not paragraphs:
            raise RuntimeError("V7_DISCLOSURE_LLM_EMPTY: 中文生成返回空段落")
        return paragraphs

    def _generate_section(self, case_id, sec, understanding, evidence_store, strategy):
        kind = sec["kind"]
        para_idx = 1
        paragraphs: list[GroundedParagraph] = []

        def para(text: str, facts=None, evidence=None) -> GroundedParagraph:
            nonlocal para_idx
            pid = f"DISC-{sec['section_id']}-P{para_idx:03d}"
            para_idx += 1
            text = _clean_html(text)  # never ship <sub>/<sup> markup to the docx
            if self.term_normalizer is not None:
                text = self.term_normalizer.normalize(text)
            return GroundedParagraph(
                paragraph_id=pid, section_id=sec["section_id"], text=text,
                evidence_ids=(evidence or sec["evidence_ids"])[:6],
                fact_ids=(facts or [getattr(f, "fact_id", "") for f in sec["facts"]])[:6],
                derived_from=[getattr(f, "fact_id", "") for f in sec["facts"]][:3],
                status=EvidenceStatus.SOURCE_FACT,
                review_status=ReviewStatus.LOCKED,
            )

        if kind == "title":
            paragraphs.append(para(sec.get("title_text") or "（发明名称待确认）"))

        elif kind == "solution_parent":
            paragraphs.append(para(
                "本发明技术方案的实施包括以下技术环节，各环节的详细说明如下：",
                facts=[getattr(f, "fact_id", "") for f in sec["facts"]]))

        elif kind == "field":
            source = "；".join(
                str(getattr(s, "text", "")) for s in
                (getattr(understanding, "technical_field", []) or [])[:4]
            )
            texts = self._llm_paragraphs(
                "说明本发明所属技术领域及具体应用场景。", source, 2)
            for t in texts:
                paragraphs.append(para(t))
            # deterministic fallback paragraph if LLM produced nothing useful
            if not paragraphs and source:
                paragraphs.append(para(f"本发明涉及{source}领域的技术方案。"))

        elif kind == "background":
            problems = "\n".join(
                f"- {str(getattr(s, 'text', ''))}" for s in
                (getattr(understanding, "technical_problems", []) or [])[:6]
            )
            facts_text = self._facts_text(sec["facts"], 4)
            source = f"### 现有技术不足\n{problems or facts_text or '（基于参考材料归纳）'}\n"
            source += self._evidence_excerpts(evidence_store, sec["evidence_ids"])
            texts = self._llm_paragraphs(
                "重构背景技术：识别最接近的现有技术路线类别，说明其技术不足，"
                "自然过渡到本发明要解决的问题。不要复述论文引言。", source, 6)
            for t in texts:
                paragraphs.append(para(t))

        elif kind == "invention":
            problems = "；".join(
                str(getattr(s, "text", "")) for s in
                (getattr(understanding, "technical_problems", []) or [])[:5]
            )
            overview = "；".join(
                str(getattr(s, "text", "")) for s in
                (getattr(understanding, "system_overview", []) or [])[:5]
            )
            effects = "；".join(
                str(getattr(s, "text", "")) for s in
                (getattr(understanding, "technical_effects", []) or [])[:6]
            )
            invent = str(getattr(strategy, "inventive_concept", ""))
            source = (f"### 要解决的技术问题\n{problems}\n\n"
                      f"### 总体构思\n{invent or overview}\n\n"
                      f"### 技术效果\n{effects or '（基于技术特征归纳）'}")
            texts = self._llm_paragraphs(
                "发明内容：先写'4.1 要解决的技术问题'，再写'4.2 总体技术构思'"
                "（从问题到手段的技术逻辑链），最后写'4.3 有益效果'"
                "（每个效果说明其技术机理，避免营销用语）。三段之间用空行分隔。",
                source, 5)
            for t in texts:
                paragraphs.append(para(t))

        elif kind == "solution":
            # technical chain subsection (5.N): title generated with content
            facts_text = self._facts_text(sec["facts"], 12)
            excerpts = self._evidence_excerpts(evidence_store, sec["evidence_ids"], limit=6)
            context = f"### 该环节的技术事实（英文原文）\n{facts_text}\n\n### 原始证据摘录\n{excerpts}"
            texts = self._llm_paragraphs(
                "技术方案详细说明的一个环节：把事实组织成连贯的技术逻辑"
                "（输入→处理→输出），包含关键参数与公式（公式保留原文）。"
                "第一段的第一句话用'本环节'开头描述该环节主题。", context, 4)
            for t in texts:
                paragraphs.append(para(t))

        elif kind == "figures":
            fig_lines = []
            for figure in sec.get("figures", []) or []:
                provenance = getattr(figure, "provenance", "") or "generated"
                if provenance == "omitted":
                    continue
                fig_lines.append(
                    f"- 图{getattr(figure, 'number', '?')}：{getattr(figure, 'title', '')}"
                )
            if fig_lines:
                intro = para(
                    f"本技术方案包含以下{len(fig_lines)}幅附图：\n" + "\n".join(fig_lines),
                    facts=[f.get("fact_id", "") for f in sec["facts"]],
                )
                paragraphs.append(intro)
            else:
                paragraphs.append(para("附图待用户补充。"))

        elif kind == "embodiment":
            phase = sec.get("phase", "实施细节")
            facts_text = self._facts_text(sec["facts"], 14)
            excerpts = self._evidence_excerpts(evidence_store, sec["evidence_ids"], limit=7)
            context = f"### 实施例相关技术事实\n{facts_text}\n\n### 原始证据摘录\n{excerpts}"
            texts = self._llm_paragraphs(
                f"具体实施方式-实施例（主题：{phase}）：给出可实施的具体步骤，"
                "步骤化描述（S1/S2/S3 或第一/第二…），包含输入、处理、参数、输出、"
                "条件及关键数值（数值必须来自材料）。", context, 6)
            for t in texts:
                paragraphs.append(para(t))

        elif kind == "agency":
            core = []
            for statement in getattr(strategy, "independent_claim_core", []) or []:
                core.append(f"- {str(getattr(statement, 'text', ''))}")
            extra = []
            for label, items in (
                ("支持缺口", getattr(strategy, "support_gaps", []) or []),
                ("风险提示", getattr(strategy, "risks", []) or []),
            ):
                for item in items[:4]:
                    extra.append(f"- [{label}] {str(item)}")
            source = "### 核心发明点\n" + "\n".join(core) + "\n\n### 策略信息\n" + "\n".join(extra)
            texts = self._llm_paragraphs(
                "以代理师友好列表形式，标注需重点说明的核心技术特征、"
                "术语定义建议、支持证据位置及注意事项。", source, 3)
            for t in texts:
                paragraphs.append(para(t))

        elif kind == "questions":
            questions = [
                str(getattr(q, "text", "")) for q in
                (getattr(understanding, "uncertainties", []) or [])[:8]
            ]
            strategy_qs = [str(q) for q in (getattr(strategy, "inventor_questions", []) or [])[:8]]
            all_q = list(dict.fromkeys(questions + strategy_qs))
            source = "\n".join(f"- {q}" for q in all_q) if all_q else "（暂无可确认项，请发明人补充实际应用中的参数选择。）"
            texts = self._llm_paragraphs(
                "列出材料中缺失、需要发明人或代理机构进一步确认的技术信息，"
                "如关键参数取值、应用场景、变型方案等。", source, 3)
            for t in texts:
                paragraphs.append(para(t))

        title = sec["title"] or self._default_title(sec)
        return GroundedSection(section_id=sec["section_id"], title=title, paragraphs=paragraphs)

    def _default_title(self, sec) -> str:
        kind = sec["kind"]
        if kind == "solution":
            num = int(sec["section_id"].split("-")[1])
            return f"5.{num} 技术环节{num}"
        if kind == "embodiment":
            cn = CN_NUMERALS[min(int(sec["section_id"].split("-")[1]) - 1, 9)]
            return f"7. 实施例{cn}：{sec.get('phase', '')}详细说明"
        return sec["title"]


def generate_chinese_claims(title: str, strategy, understanding, provider,
                            cache_dir=None) -> "GroundedClaimSet":
    """Native-Chinese claim features from the protection strategy.

    Feature ids / source_fact_ids / evidence_ids preserved; only the prose
    is Chinese (formulas and symbols kept verbatim).
    """
    from patent_agent.core.models import ClaimFeature, GroundedClaimSet, PatentClaimV2

    statements = [s for s in (getattr(strategy, "independent_claim_core", []) or [])]
    items = "\n".join(
        f"[{i}] {str(getattr(s, 'text', ''))}" for i, s in enumerate(statements, 1)
    )
    prompt = (
        "请把以下英文权利要求特征翻译为中文专利权利要求语言，"
        "逐条一一对应输出：\n\n" + items + "\n\n"
        "要求：\n"
        "1. 输出 JSON 数组 [{\"index\": 1, \"text\": \"...\"}, ...]；\n"
        "2. 中文专利表达（包括：其特征在于、所述等）；\n"
        "3. 数学符号、公式、拉丁缩写、数字原样保留；\n"
        "4. 不增删技术内容。"
    )
    text = _text_retry(provider, system_prompt=CHINESE_STYLE_RULES, user_prompt=prompt,
                       cache_dir=cache_dir)
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise RuntimeError("V7_CLAIMS_LLM_FAILED: 权利要求特征中文生成失败")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"V7_CLAIMS_LLM_FAILED: JSON 解析失败: {exc}") from exc

    by_index = {item["index"]: item["text"] for item in parsed}
    from patent_agent.v7_1.quality import TechnicalTerminologyNormalizer
    normalizer = TechnicalTerminologyNormalizer.from_source_texts(
        [str(getattr(fact, "statement", "")) for fact in (getattr(understanding, "facts", []) or [])]
        + [str(getattr(statement, "text", "")) for statement in statements]
    )
    features = []
    for i, statement in enumerate(statements, 1):
        facts = [
            f for f in (getattr(understanding, "facts", []) or [])
            if set(getattr(f, "evidence_ids", []) or []) & set(getattr(statement, "evidence_ids", []) or [])
            and getattr(f, "review_status", None) != ReviewStatus.REJECTED
        ]
        zh_text = by_index.get(i) or str(getattr(statement, "text", ""))
        zh_text = _clean_html(zh_text)
        zh_text = normalizer.normalize(zh_text)
        features.append(ClaimFeature(
            feature_id=f"CORE-F{i:03d}", text=zh_text,
            source_fact_ids=[getattr(f, "fact_id", "") for f in facts],
            evidence_ids=getattr(statement, "evidence_ids", []) or [],
            support_status="SUPPORTED" if facts and getattr(statement, "evidence_ids", []) else "UNSUPPORTED",
            mandatory=True,
        ))
    rendered = "一种经人工审查的技术方法，其特征在于，包括：" + \
               "；".join(f.text.rstrip("。；") for f in features) + "。"
    return GroundedClaimSet(
        title=title,
        claims=[PatentClaimV2(
            claim_number=1, claim_type="method", features=features,
            rendered_text=rendered, draft_strategy=getattr(strategy, "scope_strategy", "").lower(),
        )],
    )
