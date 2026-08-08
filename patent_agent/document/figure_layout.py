"""Figure layout stabilization V6.6 - BBox, collision detection, reflow, validators.

Every rendered element (node box, title, text, math image, arrow segment)
gets a BBox. After the initial layout pass, collisions are detected and
the layout auto-reflows (increase gaps -> widen columns -> grow canvas)
until no overlap remains or the attempt budget is exhausted.

Validators consume the layout report JSON that the renderer writes next
to each PNG, plus the FigureSpec itself for semantic checks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


# ── BBox ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BBox:
    """Axis-aligned box in canvas pixel coordinates."""
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2

    def overlaps(self, other: "BBox", pad: float = 0.0) -> bool:
        """True if boxes intersect after expanding `other` by pad px."""
        if self.w <= 0 or self.h <= 0 or other.w <= 0 or other.h <= 0:
            return False
        return not (
            self.x >= other.x1 + pad
            or self.x1 <= other.x - pad
            or self.y >= other.y1 + pad
            or self.y1 <= other.y - pad
        )

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.w, self.h]

    @staticmethod
    def from_points(pts: Iterable[tuple[float, float]]) -> "BBox":
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if not xs:
            return BBox(0, 0, 0, 0)
        return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


@dataclass
class LayoutElement:
    """One drawn element with its recorded bbox."""
    kind: str  # "node" | "text" | "math" | "arrow" | "title" | "source_image"
    bbox: BBox
    node_id: str = ""
    content: str = ""
    column: str = ""  # "left" | "right" | "center" | ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "bbox": self.bbox.to_list(),
            "node_id": self.node_id,
            "content": self.content[:80],
            "column": self.column,
        }


@dataclass
class Collision:
    a_kind: str
    a_id: str
    b_kind: str
    b_id: str
    type: str  # text-text | text-node | node-node | arrow-text | arrow-math | arrow-node | title-node

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Collision detection ──────────────────────────────────────────

_COLLISION_PAIRS: list[tuple[str, str, str]] = [
    # (kind_a, kind_b, collision_type)
    ("text", "text", "text-text"),
    ("text", "node", "text-node"),
    ("math", "text", "math-text"),
    ("math", "math", "math-math"),
    ("math", "node", "math-node"),
    ("node", "node", "node-node"),
    ("arrow", "text", "arrow-text"),
    ("arrow", "math", "arrow-math"),
    ("arrow", "node", "arrow-node"),
    ("title", "node", "title-node"),
    ("title", "text", "title-text"),
]


class CollisionDetector:
    """Detect overlaps between recorded element bboxes."""

    def __init__(self, pad: float = 2.0):
        self.pad = pad

    @staticmethod
    def _endpoints(node_id: str) -> set[str]:
        """'A1->A2' -> {'A1','A2'}; plain ids unchanged."""
        if "->" in node_id:
            a, _, b = node_id.partition("->")
            return {a.strip(), b.strip()}
        return set()

    def detect(self, elements: list[LayoutElement]) -> list[Collision]:
        collisions: list[Collision] = []
        # Same-node text/math elements intentionally live inside their own
        # box: skip intra-node comparisons for (text,math) inside a node.
        grouped: dict[str, list[LayoutElement]] = {}
        for el in elements:
            grouped.setdefault(el.node_id, []).append(el)

        # Nodes vs everything else
        nodes = [el for el in elements if el.kind == "node"]
        others = [el for el in elements if el.kind != "node"]

        # node-node
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if nodes[i].bbox.overlaps(nodes[j].bbox, self.pad):
                    collisions.append(Collision("node", nodes[i].node_id, "node", nodes[j].node_id, "node-node"))

        # non-node vs node. Arrows/labels starting and ending exactly at a
        # node's boundary are expected -> skip the arrow's own endpoints and
        # use pad 0 for arrows (a real crossing of a box interior still
        # reports).
        for el in others:
            own_ends = self._endpoints(el.node_id)
            for nd in nodes:
                if el.node_id == nd.node_id or nd.node_id in own_ends:
                    continue
                pad = 0.0 if el.kind == "arrow" else self.pad
                if el.bbox.overlaps(nd.bbox, pad):
                    collisions.append(Collision(el.kind, el.node_id, "node", nd.node_id, f"{el.kind}-node"))

        # non-node vs non-node of different kinds where relevant
        texts = [el for el in elements if el.kind in ("text", "math")]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b = texts[i], texts[j]
                if a.node_id and a.node_id == b.node_id:
                    continue  # same box, vertically stacked
                if a.bbox.overlaps(b.bbox, self.pad):
                    collisions.append(Collision(a.kind, a.node_id, b.kind, b.node_id, f"{a.kind}-{b.kind}"))

        # arrows vs texts/maths (arrows already covered vs nodes above).
        # An arrow never collides with its own label (same node_id) and an
        # arrow touching its own endpoint box boundary is expected, so pad=0.
        arrows = [el for el in elements if el.kind == "arrow"]
        for ar in arrows:
            for el in texts:
                if ar.node_id and ar.node_id == el.node_id:
                    continue
                if ar.bbox.overlaps(el.bbox, 0.0):
                    collisions.append(Collision("arrow", ar.node_id, el.kind, el.node_id, f"arrow-{el.kind}"))
        return collisions


# ── Layout report ────────────────────────────────────────────────

@dataclass
class LayoutReport:
    figure_id: str = ""
    number: int = 0
    layout: str = ""
    canvas: dict[str, int] = field(default_factory=dict)
    title_bbox: list[float] = field(default_factory=list)
    elements: list[LayoutElement] = field(default_factory=list)
    collisions: list[Collision] = field(default_factory=list)
    reflow_attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "number": self.number,
            "layout": self.layout,
            "canvas": self.canvas,
            "title_bbox": self.title_bbox,
            "elements": [e.to_dict() for e in self.elements],
            "collisions": [c.to_dict() for c in self.collisions],
            "reflow_attempts": self.reflow_attempts,
        }

    def save(self, path: Path) -> Path:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutReport":
        elements = [
            LayoutElement(kind=e["kind"], bbox=BBox(*e["bbox"]),
                          node_id=e.get("node_id", ""), content=e.get("content", ""),
                          column=e.get("column", ""))
            for e in data.get("elements", [])
        ]
        collisions = [Collision(a_kind=c["a_kind"], a_id=c["a_id"],
                                b_kind=c["b_kind"], b_id=c["b_id"], type=c["type"])
                      for c in data.get("collisions", [])]
        return cls(
            figure_id=data.get("figure_id", ""),
            number=data.get("number", 0),
            layout=data.get("layout", ""),
            canvas=data.get("canvas", {}),
            title_bbox=data.get("title_bbox", []),
            elements=elements,
            collisions=collisions,
            reflow_attempts=data.get("reflow_attempts", 0),
        )

    @classmethod
    def from_file(cls, path: Path) -> "LayoutReport":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# ── Validators ───────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    code: str
    severity: str  # ERROR | WARNING | INFO
    message: str
    figure: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FigureLayoutValidator:
    """Validates a rendered figure's layout report for overlaps/overflow."""

    def validate(self, report: LayoutReport | dict | Path | None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if report is None:
            issues.append(ValidationIssue("NO_LAYOUT_REPORT", "ERROR", "缺少布局报告", ""))
            return issues
        if isinstance(report, Path) or isinstance(report, str):
            report = LayoutReport.from_file(Path(report))
        elif isinstance(report, dict):
            report = LayoutReport.from_dict(report)
        fid = f"图{report.number}"

        # 1. overlap count
        if report.collisions:
            issues.append(ValidationIssue(
                "OVERLAP", "ERROR",
                f"{len(report.collisions)}处元素重叠: {', '.join(c.type for c in report.collisions[:5])}",
                fid))
        # 2. overflow: any element extends beyond canvas
        cw, ch = report.canvas.get("w", 0), report.canvas.get("h", 0)
        if cw and ch:
            for el in report.elements:
                if el.bbox.x < 0 or el.bbox.y < 0 or el.bbox.x1 > cw or el.bbox.y1 > ch:
                    issues.append(ValidationIssue(
                        "OVERFLOW", "ERROR",
                        f"元素 {el.kind}:{el.node_id} 超出画布 ({el.bbox.to_list()})",
                        fid))
        # 3. node visibility: every node non-empty and inside canvas
        nodes = [e for e in report.elements if e.kind == "node"]
        for el in nodes:
            if el.bbox.w <= 0 or el.bbox.h <= 0:
                issues.append(ValidationIssue("NODE_INVISIBLE", "ERROR", f"节点 {el.node_id} 不可见", fid))
        # 4. title visibility
        if report.title_bbox:
            tx, ty, tw, th = report.title_bbox
            if ty < 0 or ty + th > ch:
                issues.append(ValidationIssue("TITLE_CUT", "ERROR", "图题被裁切", fid))
        return issues


class FigureSemanticValidator:
    """Checks figure-specific semantic requirements."""

    def validate(self, figure, report: LayoutReport | dict | Path | None = None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        nodes = {n.id: (n.label or "") for n in figure.nodes}
        edges = [(e.source, e.target) for e in figure.edges]
        fid = f"图{figure.number}"
        layout = getattr(figure, "layout", "auto") or "auto"

        # ── Figure 3: LDM training/generation two paths ──
        if "训练" in figure.title and "生成" in figure.title:
            has_training = any("训练" in v or k.startswith("T") for k, v in nodes.items())
            has_generation = any("生成" in v or k.startswith("G") for k, v in nodes.items())
            if not has_training:
                issues.append(ValidationIssue("NO_TRAINING_PATH", "ERROR", "缺少训练路径", fid))
            if not has_generation:
                issues.append(ValidationIssue("NO_GENERATION_PATH", "ERROR", "缺少生成路径", fid))
            if layout not in ("two_column", "branch_merge"):
                issues.append(ValidationIssue("WRONG_LAYOUT", "WARNING", f"图3应为双栏布局，当前: {layout}", fid))
            # bridge edge between paths
            bridge = [e for e in edges if e[0].startswith("T") and e[1].startswith("G")] or \
                     [e for e in edges if e[0].startswith("G") and e[1].startswith("T")]
            if not bridge:
                issues.append(ValidationIssue("NO_PARAMETER_BRIDGE", "WARNING", "缺少训练→生成参数传递连接", fid))

        # ── Figure 4: dual input Z1/Z2 merge ──
        if "插值" in figure.title or "潜在空间" in figure.title:
            ids = set(nodes)
            has_z1 = any("Z_1" in v or "Z1" in v or "Z₁" in v for v in nodes.values())
            has_z2 = any("Z_2" in v or "Z2" in v or "Z₂" in v for v in nodes.values())
            if not (has_z1 and has_z2):
                issues.append(ValidationIssue("NO_DUAL_INPUT", "ERROR", "缺少 Z₁/Z₂ 双输入", fid))
            merge_targets = [t for _, t in edges if sum(1 for s, tt in edges if tt == t) >= 2]
            if not merge_targets:
                issues.append(ValidationIssue("NO_MERGE_NODE", "ERROR", "缺少双输入合流节点", fid))
            out_edges = [s for s, t in edges if s in merge_targets]
            if not out_edges:
                issues.append(ValidationIssue("NO_MERGE_OUTPUT", "ERROR", "合流节点无输出", fid))

        # ── Figure 2: real structure or explicit omission ──
        if "转子设计变量" in figure.title or "设计变量标注" in figure.title:
            prov = getattr(figure, "provenance", "") or "generated"
            if prov == "omitted":
                issues.append(ValidationIssue("FIGURE_OMITTED", "INFO", "图2已标记为待用户补充（未嵌入推荐版）", fid))
            elif prov != "extracted" and prov != "uploaded":
                issues.append(ValidationIssue("FAKE_STRUCTURE_FIGURE", "ERROR",
                                              f"图2来源为 {prov}，结构示意图必须为真实图或明确标记待补充", fid))
        return issues


class FigureSourceValidator:
    """Checks source provenance is explicit for every figure."""

    KNOWN = {"generated", "extracted", "uploaded", "omitted"}

    def validate(self, figures) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for fig in figures:
            prov = getattr(fig, "provenance", "") or "generated"
            fid = f"图{fig.number}"
            if prov not in self.KNOWN:
                issues.append(ValidationIssue("UNKNOWN_PROVENANCE", "ERROR",
                                              f"未知来源 {prov!r}", fid))
            if prov == "extracted" and not (getattr(fig, "png_path", "") or ""):
                issues.append(ValidationIssue("EXTRACTED_WITHOUT_IMAGE", "ERROR",
                                              "声明提取但无图片路径", fid))
        return issues
