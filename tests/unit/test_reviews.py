from patent_agent.agents import ClaimsWriter, DisclosureWriter, FigurePlanner, InventionMiningAgent, ProtectionStrategyAgent, TechnicalUnderstandingAgent
from patent_agent.review import hallucination_guard, review_claim_support
from tests.unit.test_agents import chunks


def test_claim_support_and_hallucination_guard_pass_grounded_demo():
    knowledge = TechnicalUnderstandingAgent().run(chunks())
    candidate = InventionMiningAgent().run(knowledge)[0]
    strategy = ProtectionStrategyAgent().run(candidate, knowledge)
    figures = FigurePlanner().run(knowledge)
    claims = ClaimsWriter().run("测试", knowledge, strategy)
    draft = DisclosureWriter().run("测试", knowledge, strategy, figures)
    assert review_claim_support(claims, knowledge.evidence) == []
    assert hallucination_guard(draft, knowledge) == []

