"""Global concept registry and per-case concept detection (V7).

This is a *controlled vocabulary* of distinguishable generative-method
concepts - not case content. Each real case has a detected concept
fingerprint derived from ITS OWN evidence. Cross-case contamination is
detected when an output uses a concept that belongs to another case's
fingerprint but not to the current case's.

Also hosts the fixture/demo lexicon used by PlaceholderLeakValidator:
words that only ever come from template/test material must never appear
in a real case's output.
"""
from __future__ import annotations

import re
from typing import Iterable

# ── Concept families: distinctive generative/optimization methods ──────────
# Each family has EN + ZH keywords. A case whose evidence never mentions a
# family may not emit it in disclosure text or figures.
CONCEPT_FAMILIES: dict[str, dict[str, list[str]]] = {
    "latent_diffusion": {
        "label_zh": "潜在扩散",
        "en": ["latent diffusion", "diffusion model", "forward diffusion",
               "reverse diffusion", "reverse denoising", "noise prediction",
               "denoising", "ddpm", "ddim", "unet", "u-net", "noise schedule",
               "additive gaussian noise", "markov chain", "denoise"],
        "zh": ["潜在扩散", "扩散模型", "前向扩散", "反向扩散", "反向去噪",
               "噪声预测", "去噪", "u-net", "加噪", "马尔可夫链"],
    },
    "flow_matching": {
        "label_zh": "流匹配",
        "en": ["flow matching", "velocity field", "probability flow",
               "optimal transport", "transport", "reflow", "ode integration",
               "flow-matching", "conditional flow"],
        "zh": ["流匹配", "速度场", "概率流", "最优传输", "传输", "ode积分"],
    },
    "vae": {
        "label_zh": "变分自编码器",
        "en": ["variational autoencoder", "autoencoder", "latent variable",
               "encoder", "decoder", "posterior", "kl divergence",
               "reparameterization", "reconstruction loss", "vae"],
        "zh": ["变分自编码器", "自编码器", "潜在变量", "编码器", "解码器",
               "后验分布", "kl散度", "重参数化", "重构损失"],
    },
    "surrogate": {
        "label_zh": "代理模型",
        "en": ["surrogate", "feature-wise", "feature wise", "filim", "fi lm",
               "prediction model", "regression model", "multi-level",
               "modulation", "latent conditioning", "conditioning"],
        "zh": ["代理模型", "特征线性调制", "预测模型", "回归模型", "条件调制"],
    },
    "generative_gan": {
        "label_zh": "生成对抗网络",
        "en": ["generative adversarial", "gan", "discriminator", "generator network"],
        "zh": ["生成对抗网络", "判别器", "生成器网络"],
    },
    "optimization": {
        "label_zh": "优化",
        "en": ["nsga", "current vector", "current-vector", "multi-objective",
               "pareto", "objective function", "optimization loop",
               "design variables", "coupled optimization", "genetic algorithm"],
        "zh": ["电流矢量", "多目标优化", "帕累托", "目标函数", "优化循环",
               "设计变量", "耦合优化", "遗传算法"],
    },
    "fea_simulation": {
        "label_zh": "有限元仿真",
        "en": ["finite element", "fea", "magnetostatic", "magnetic flux",
               "flux linkage", "torque", "cogging", "ferrite", "lamination",
               "synchronous reluctance", "rotor topology", "permanent magnet"],
        "zh": ["有限元", "静磁场", "磁链", "转矩", "铁氧体", "叠片",
               "同步磁阻", "转子拓扑", "永磁体"],
    },
    "data_generation": {
        "label_zh": "数据构建",
        "en": ["dataset", "sampling", "latin hypercube", "parameterised",
               "parameterized", "training set", "validation set", "test set",
               "augmentation", "synthetic data"],
        "zh": ["数据集", "采样", "拉丁超立方", "参数化", "训练集", "验证集", "测试集"],
    },
}

# Concepts that are NOT method-specific and may appear in any case (won't be
# treated as contamination evidence).
UNIVERSAL_CONCEPTS = {"fea_simulation", "data_generation", "vae"}


def concept_keywords(concept: str) -> list[str]:
    """Return all keywords (EN + ZH) for a concept family."""
    fam = CONCEPT_FAMILIES[concept]
    return fam["en"] + fam["zh"]


def detect_case_concepts(text_blocks: Iterable[str]) -> set[str]:
    """Detect concept families present in a case's own evidence text.

    Returns the set of concept family keys that have at least one keyword
    hit in the joined text.
    """
    joined = " ".join(str(block) for block in text_blocks).lower()
    found: set[str] = set()
    for concept, fam in CONCEPT_FAMILIES.items():
        for kw in fam["en"] + fam["zh"]:
            if kw.lower() in joined:
                found.add(concept)
                break
    return found


def concept_labels(concepts: Iterable[str]) -> dict[str, str]:
    """Map concept keys to their Chinese labels (for figure titles etc.)."""
    return {c: CONCEPT_FAMILIES[c]["label_zh"] for c in concepts if c in CONCEPT_FAMILIES}


def forbidden_concepts_for(case_concepts: set[str], other_cases: dict[str, set[str]]) -> set[str]:
    """Concepts owned by OTHER cases but absent from this case's evidence.

    `other_cases` maps case_id -> detected concept set (from their manifests/
    fingerprints). Any concept that appears in another case's fingerprint but
    not in this case's own evidence is a contamination risk if emitted here.
    """
    foreign = set()
    for other_case, concepts in other_cases.items():
        if not other_case:
            continue
        foreign |= concepts
    return foreign - case_concepts


# ── Fixture / demo / template lexicon ──────────────────────────────────────
# These phrases only exist in demo materials and templates; they must never
# appear in a real case's patent output (PlaceholderLeakValidator).
FIXTURE_LEXICON: list[str] = [
    "融合状态量",            # demo/motor_control fixture term
    "控制参数修正",          # demo/motor_control fixture term
    "多源信号采集",          # demo/motor_control fixture term
    "自适应控制指令",        # demo/motor_control fixture term
    "状态监测与自适应控制",  # demo/motor_control fixture term
    "振动监测",              # demo/motor_control fixture term
    "multi-source signal",   # demo fixture term (en)
    "fused state",           # demo fixture term (en)
    "adaptive control command",  # demo fixture term (en)
    "sensor confidence",     # demo fixture term (en)
    "demo case",             # fixture marker
    "synthetic demo",        # fixture marker
    "demo material",         # fixture marker
]

# Explicit hard-coded sentences that previously leaked from the legacy demo
# AST factory into real-case output (kept as a regression guard).
LEGACY_DEMO_SENTENCES: list[str] = [
    "在控制过程中，电磁转矩",
    "作为状态量参与控制参数修正",
    "计算融合状态量，并据此生成控制参数修正量",
    "从多源信号采集到自适应控制指令输出",
    "状态采集单元",
    "状态估计单元",
]


def fixture_violations(text: str) -> list[str]:
    """Return all fixture/demo phrases found in a text."""
    lowered = text.lower()
    hits = [phrase for phrase in FIXTURE_LEXICON + LEGACY_DEMO_SENTENCES if phrase.lower() in lowered]
    return hits
