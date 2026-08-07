import re
from patent_agent.core.models import PatentKnowledge, ReviewFinding


def review_symbols(knowledge: PatentKnowledge) -> list[ReviewFinding]:
    findings = []
    for equation in knowledge.equations:
        candidates = set(re.findall(r"(?<!\\)\b[A-Za-z](?:_[A-Za-z]+)?\b", equation.latex))
        undefined = sorted(symbol for symbol in candidates if symbol not in equation.symbols and symbol.split("_", 1)[0] not in equation.symbols and symbol not in {"e", "dt"})
        if undefined:
            findings.append(ReviewFinding(code="SYMBOL_UNDEFINED", severity="WARNING", message=f"{equation.id}可能存在未定义符号：{', '.join(undefined)}", location=equation.id))
    return findings
