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
    """Check the declarative graph contract without domain-specific rules."""

    def validate(self, figure, report: LayoutReport | dict | Path | None = None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        nodes = {n.id: (n.label or "") for n in figure.nodes}
        edges = {(e.source, e.target) for e in figure.edges}
        fid = f"图{figure.number}"
        for edge in edges:
            if edge[0] not in nodes or edge[1] not in nodes:
                issues.append(ValidationIssue("DANGLING_ARROW", "ERROR", "连接端点不是已声明节点", fid))
        for node_id in getattr(figure, "required_node_ids", []) or []:
            if node_id not in nodes:
                issues.append(ValidationIssue("REQUIRED_NODE_MISSING", "ERROR", f"缺少必需节点 {node_id}", fid))
        for edge_id in getattr(figure, "required_edge_ids", []) or []:
            source, separator, target = edge_id.partition("->")
            if not separator or (source, target) not in edges:
                issues.append(ValidationIssue("REQUIRED_EDGE_MISSING", "ERROR", f"缺少必需连接 {edge_id}", fid))
        layout = getattr(figure, "layout", "auto") or "auto"
        if layout == "two_column":
            left = set(getattr(figure, "left_node_ids", []) or [])
            right = set(getattr(figure, "right_node_ids", []) or [])
            if left and not left <= set(nodes):
                issues.append(ValidationIssue("NO_TRAINING_PATH", "ERROR", "双栏图缺少左栏声明节点", fid))
            if right and not right <= set(nodes):
                issues.append(ValidationIssue("NO_GENERATION_PATH", "ERROR", "双栏图缺少右栏声明节点", fid))
            if left and right and not any(source in left and target in right for source, target in edges):
                issues.append(ValidationIssue("NO_PARAMETER_BRIDGE", "ERROR", "双栏图缺少跨栏连接", fid))
        if layout == "branch_merge":
            incoming = {node_id: sum(1 for _, target in edges if target == node_id) for node_id in nodes}
            merge_nodes = {node_id for node_id, degree in incoming.items() if degree >= 2}
            if not merge_nodes:
                issues.append(ValidationIssue("NO_MERGE_NODE", "ERROR", "分支合流图缺少合流节点", fid))
            elif not any(source in merge_nodes for source, _ in edges):
                issues.append(ValidationIssue("NO_MERGE_OUTPUT", "ERROR", "合流节点缺少输出", fid))
        provenance = getattr(figure, "provenance", "") or "generated"
        if provenance == "extracted" and not getattr(figure, "source_figure_ref", ""):
            issues.append(ValidationIssue("SOURCE_FIGURE_REF_MISSING", "ERROR", "提取图缺少案例内来源引用", fid))
        if getattr(figure, "source_figure_ref", "") and provenance not in {"extracted", "uploaded"}:
            issues.append(ValidationIssue("FAKE_STRUCTURE_FIGURE", "ERROR", "带来源引用的结构图必须使用真实提取或上传图", fid))
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
