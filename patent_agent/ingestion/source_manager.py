from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from patent_agent.core.models import SourceChunk, SourceFileRecord
from patent_agent.core.state import CaseStore
from .readers import read_docx, read_pdf, read_pptx, read_text


READERS = {".txt": read_text, ".md": read_text, ".docx": read_docx, ".pdf": read_pdf, ".pptx": read_pptx}
IMAGES = {".png", ".jpg", ".jpeg"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_markdown(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    if len(parts) == 1:
        return [("全文", text)]
    result = []
    if parts[0].strip(): result.append(("前言", parts[0].strip()))
    for index in range(1, len(parts), 2):
        result.append((parts[index].strip(), parts[index + 1].strip()))
    return result


class SourceManager:
    def __init__(self, store: CaseStore):
        self.store = store

    def ingest(self, case_id: str, inputs: list[Path]) -> tuple[list[SourceFileRecord], list[SourceChunk], list[dict]]:
        paths: list[Path] = []
        for item in inputs:
            paths.extend(sorted(p for p in item.rglob("*") if p.is_file()) if item.is_dir() else [item])
        records: list[SourceFileRecord] = []
        chunks: list[SourceChunk] = []
        images: list[dict] = []
        counter = 1
        for original in paths:
            suffix = original.suffix.lower()
            if suffix not in READERS and suffix not in IMAGES:
                continue
            stored = self.store.import_source_file(case_id, original)
            file_hash = digest(stored)
            if suffix in IMAGES:
                images.append({"id": f"IMG-{len(images)+1:03d}", "file": str(stored), "original": str(original), "suggested_number": len(images)+1, "nearby_text": "", "description": "[待人工补充图片说明]"})
                records.append(SourceFileRecord(path=str(stored), original_path=str(original), media_type="image", sha256=file_hash))
                continue
            blocks = split_markdown(stored.read_text(encoding="utf-8")) if suffix == ".md" else READERS[suffix](stored)
            chunk_ids = []
            for heading, text in blocks:
                if not text.strip(): continue
                chunk_id = f"P{counter:03d}"; counter += 1; chunk_ids.append(chunk_id)
                chunks.append(SourceChunk(id=chunk_id, source_file=stored.name, source_location=heading, heading=heading, text=text.strip(), sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()))
            records.append(SourceFileRecord(path=str(stored), original_path=str(original), media_type=suffix.lstrip("."), sha256=file_hash, chunk_ids=chunk_ids))
        case = self.store.load(case_id); case.source_files = records; self.store.save_case(case)
        case_dir = self.store.case_dir(case_id)
        (case_dir / "working" / "source_chunks.json").write_text(json.dumps([c.model_dump() for c in chunks], ensure_ascii=False, indent=2), encoding="utf-8")
        (case_dir / "figures" / "image_manifest.json").write_text(json.dumps(images, ensure_ascii=False, indent=2), encoding="utf-8")
        return records, chunks, images

