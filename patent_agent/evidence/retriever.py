from __future__ import annotations

import math
import re
from collections import Counter

from patent_agent.core.models import EvidenceChunk, EvidenceScope


class EvidenceRetriever:
    """Small deterministic BM25-like retriever; no embedding service required."""

    def __init__(self, store):
        self.store = store

    def retrieve(self, query: str, top_k: int = 10, scope: EvidenceScope | None = EvidenceScope.INVENTION_SOURCE) -> list[EvidenceChunk]:
        chunks = self.store.all(scope=scope)
        if not chunks:
            return []
        tokenized = [_tokens(item.normalized_text) + _tokens(item.section_title or "") * 3 for item in chunks]
        query_tokens = _tokens(query)
        document_frequency = Counter(token for tokens in tokenized for token in set(tokens))
        average_length = sum(len(tokens) for tokens in tokenized) / len(tokenized)
        scored = []
        for chunk, tokens in zip(chunks, tokenized):
            counts = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                if not counts[token]:
                    continue
                idf = math.log(1 + (len(chunks) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
                frequency = counts[token]
                denominator = frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(average_length, 1))
                score += idf * frequency * 2.2 / denominator
                if chunk.section_title and token in _tokens(chunk.section_title):
                    score += idf * 0.75
            scored.append((score, chunk))
        ranked = [chunk for score, chunk in sorted(scored, key=lambda item: (-item[0], item[1].evidence_id)) if score > 0]
        return ranked[:top_k] if ranked else chunks[:top_k]


def _tokens(value: str) -> list[str]:
    lowered = value.lower()
    ascii_words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    bigrams = [chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))]
    return ascii_words + bigrams
