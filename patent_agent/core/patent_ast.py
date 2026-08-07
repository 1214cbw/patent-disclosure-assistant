from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class PatentNode(BaseModel):
    type: Literal[
        "heading", "paragraph", "text", "inline_math", "display_equation",
        "figure", "figure_reference", "equation_reference", "list", "claim",
        "source_citation", "reviewer_note", "inventor_question", "page_break"
    ]
    value: str = ""
    level: int | None = None
    latex: str = ""
    number: int | None = None
    target: str = ""
    path: str = ""
    children: list["PatentNode"] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)


class PatentDocumentAST(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    kind: Literal["disclosure", "claims", "specification", "abstract"]
    title: str
    nodes: list[PatentNode]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self):
        equation_ids = {n.target for n in self.nodes if n.type == "display_equation" and n.target}
        figure_ids = {n.target for n in self.nodes if n.type == "figure" and n.target}

        def walk(nodes):
            for node in nodes:
                if node.type == "equation_reference" and node.target not in equation_ids:
                    raise ValueError(f"Broken equation reference: {node.target}")
                if node.type == "figure_reference" and node.target not in figure_ids:
                    raise ValueError(f"Broken figure reference: {node.target}")
                walk(node.children)
        walk(self.nodes)
        return self

