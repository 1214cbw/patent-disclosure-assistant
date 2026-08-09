# V7.2 Patent Semantic Basis

## Scope

This project produces an inventor/agent technical disclosure, not a filing-ready
CNIPA specification. The official rules below are therefore translated into
fact-completeness, implementation-continuity, evidence, and review gates that
help a patent professional prepare later application documents. They are not a
patentability or legal-sufficiency opinion.

## Official CNIPA sources checked on 2026-08-09

1. [中华人民共和国专利法（2020年修正）](https://www.cnipa.gov.cn/art/2020/11/23/art_524_171347.html)
   - Article 26(3) requires a clear and complete description sufficient for a
     person skilled in the art to implement the invention.
   - V7.2 consequence: a collection of disconnected modules or formulas cannot
     pass as a complete primary embodiment.

2. [中华人民共和国专利法实施细则（2023年修订）](https://www.cnipa.gov.cn/art/2023/12/21/art_98_189197.html?siteId=qingdao)
   - Rule 20 requires the detailed embodiment portion to describe in detail the
     preferred way considered by the applicant for carrying out the invention.
   - V7.2 consequence: machine specifications, loss functions, experimental
     metrics, and limitations are supporting detail unless they independently
     form a complete way of carrying out the invention.

3. [专利审查指南（CNIPA official edition）](https://www.cnipa.gov.cn/module/download/downfile.jsp?classid=0&filename=5753f257e6a04b6f8e305eb6d34ba452.pdf&showname=%E4%B8%93%E5%88%A9%E5%AE%A1%E6%9F%A5%E6%8C%87%E5%8D%97.pdf)
   - The specification must enable implementation and the technical features of
     a combined invention must be considered through their functional support
     and interaction, not as isolated labels.
   - V7.2 consequence: the primary embodiment is generated from an invention
     core graph and must preserve cooperating feature and data-flow relations.

4. [2025年《专利审查指南》修改内容解读](https://www.cnipa.gov.cn/art/2025/12/4/art_66_202935.html)
   - For AI model construction or training, the specification generally needs
     the necessary modules, hierarchy or connections, training steps and
     parameters.
   - For AI used in a concrete field or scenario, it generally needs to explain
     how the algorithm is combined with that field and how input and output data
     are internally related.
   - V7.2 consequence: every AI step has typed inputs and outputs, a supported
     scenario, evidence IDs, and a downstream consumer; missing facts become
     pending confirmation rather than invented detail.

5. [人工智能相关发明专利申请指引（试行）](https://www.cnipa.gov.cn/art/2024/12/31/art_66_196988.html)
   - CNIPA provides the official AI application guidance as an interpretation
     of the current patent-law framework.
   - V7.2 consequence: algorithms are kept tied to technical data, engineering
     objects, and concrete technical output. Unsupported cross-domain expansion
     is a hard semantic drift.

## Engineering rules derived for V7.2

- `Fact Cluster != Embodiment`; facts first populate typed graph nodes.
- A primary embodiment must connect supported inputs, operations,
  intermediate outputs, constraints, downstream use, and a concrete final
  technical result.
- Every required claim feature must map to an embodiment step and source
  evidence.
- Formula, parameter, experiment, comparison-baseline, and limitation roles do
  not independently qualify as embodiments without explicit evidence of a
  complete implementation.
- AI modules must expose supported input/output and scenario relationships.
- Alternatives and exact parameters are allowed only when evidenced or
  human-confirmed; otherwise they are excluded or sent to pending confirmation.
- Validation-only and comparison-baseline entities may appear in validation
  prose but cannot become required invention components.
- Section 5 explains mechanisms and components; Section 7 explains how the
  whole invention is carried out end to end. One-to-one repackaging is rejected.
