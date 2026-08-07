from __future__ import annotations
import json
from pathlib import Path
from patent_agent.core.models import PriorArtReference
from .provider_base import PatentSearchProvider


class ManualImportProvider(PatentSearchProvider):
    def __init__(self, path: Path):
        self.references = [PriorArtReference.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]

    def search(self, query: str) -> list[PriorArtReference]:
        terms = [term for term in query.split() if len(term) > 1]
        return sorted(self.references, key=lambda ref: sum(term in (ref.title + ref.abstract) for term in terms), reverse=True)

    def fetch(self, reference_id: str) -> PriorArtReference:
        return next(item for item in self.references if item.id == reference_id)

