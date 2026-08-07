from patent_agent.agents import ClaimsWriter, FigurePlanner, InventionMiningAgent, ProtectionStrategyAgent, TechnicalUnderstandingAgent
from patent_agent.core.models import SourceChunk


def chunks():
    return [
        SourceChunk(id="P001", source_file="demo.md", source_location="技术领域", heading="技术领域", text="电机状态监测与控制", sha256="a" * 64),
        SourceChunk(id="P002", source_file="demo.md", source_location="技术问题", heading="技术问题", text="单一反馈无法反映复合状态。", sha256="b" * 64),
        SourceChunk(id="P003", source_file="demo.md", source_location="系统组成", heading="系统组成", text="- 状态采集单元\n- 状态估计单元\n- 控制处理单元\n- 电机驱动单元", sha256="c" * 64),
        SourceChunk(id="P004", source_file="demo.md", source_location="算法流程", heading="算法流程", text="- 获取多源信号\n- 同步特征\n- 计算融合状态量\n- 输出自适应控制指令\nFORMULA EQ-001 | 融合 | z=\\alpha x+\\beta y\nSYMBOL z=融合状态量\nSYMBOL x=振动特征\nSYMBOL y=电流特征", sha256="d" * 64),
    ]


def test_structured_agents_and_claim_tree():
    knowledge = TechnicalUnderstandingAgent().run(chunks())
    candidates = InventionMiningAgent().run(knowledge)
    strategy = ProtectionStrategyAgent().run(candidates[0], knowledge)
    claims = ClaimsWriter().run("测试发明", knowledge, strategy)
    figures = FigurePlanner().run(knowledge)
    assert len(candidates) == 3
    assert len(claims.claims) == 6
    assert claims.claims[1].depends_on == [1]
    assert len(figures) >= 1  # FigurePlanner generates domain-appropriate figures
    assert len(figures[0].nodes) >= 3  # Should have multiple flow nodes
    assert figures[0].type in ("flowchart", "system", "methodology")
    assert knowledge.equations[0].source_ids == ["P004"]

