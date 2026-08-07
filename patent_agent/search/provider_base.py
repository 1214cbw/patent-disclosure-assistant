from __future__ import annotations
from abc import ABC, abstractmethod
from patent_agent.core.models import PriorArtReference


class PatentSearchProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[PriorArtReference]:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, reference_id: str) -> PriorArtReference:
        raise NotImplementedError

