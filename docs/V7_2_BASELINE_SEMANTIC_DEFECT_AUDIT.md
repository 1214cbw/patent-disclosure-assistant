# V7.2 Baseline Semantic Defect Audit

## Audit baseline

- Repository HEAD: `39cbc479e4c5df9b4570ba123d3e1c714aaac5c9`
- Working tree at audit start: clean
- Full baseline suite: 152 passed, 1 skipped, 0 failed
- Artifact: `output/real_case/REAL-PAPER-002-V7-1-REBUILD/技术交底书_v7_1.docx`
- Structured source: `output/real_case/REAL-PAPER-002-V7-1-REBUILD/disclosure_final.json`

The V7.1 delivery gates correctly protect headings, section presence, figures,
equations, terminology, OpenXML, PDF geometry, and layout. They do not protect
the patent meaning of the embodiment architecture.

## Reproduced defects

### Fact phase mapped directly to embodiment

The V7.1 planner groups technical fact clusters by `fact.category` and creates
one `07-*` section for every category. The real artifact therefore contains 16
purported embodiments, including machine specification, data representation,
loss function, mathematical expression, experiment setup, training process,
and limitation categories. This is a category-to-embodiment mapping rather
than planning complete implementations.

### Module-only and detail-only embodiments

The following V7.1 sections are not internally closed implementations:

- `07-02 机器规格`
- `07-07 损失函数`
- `07-10 数学表达`
- `07-14 实验设置`
- `07-16 局限性说明`

They describe parameters, formulas, validation material, or scope boundaries
that should support an implementation or validation section, not become an
embodiment merely because a fact category exists.

### Unsupported generalization

`07-07` expands a topology-image input to “图像、文本或其它类型的数据” and
adds alternative reconstruction losses and `λ_KL` examples `0.1` and `1.0`
without cited source support. `07-08` adds Euler and Runge-Kutta solver choices
without source support. `07-11` adds response-surface and Kriging alternatives
without evidence or an approved strategy expansion.

### Scenario drift

`07-13` turns an offline candidate-design feasibility constraint into an online
motor-control procedure with signal acquisition, position sensor or observer,
per-control-cycle execution, and real-time lookup. These are not supported by
the source evidence for the offline topology-optimization workflow.

### Comparison-baseline contamination

`07-15` lists GAN, concatenation and DeepONet components in a common training
procedure. The source uses these architectures as comparison baselines; the
V7.1 embodiment prose can therefore promote validation-only entities into the
invention implementation.

### Section 5 / Section 7 mirroring

Section 5 contains 20 technical-module subsections. Section 7 repackages the
same fact categories into 16 embodiments. The mapping is near one-to-one and
does not create an end-to-end implementation from technical input through data
generation, model training and use, optimization, and validated design output.

## Root cause

`PatentDisclosurePlanner.build_plan()` derives embodiment groups from
`_phase_of(cluster)` and emits one embodiment per phase. `_generate_section()`
then asks the language model to turn each isolated phase into executable steps.
The prompt pressure to make every fragment look executable causes fabricated
inputs, alternatives, parameters, and scenarios. No invention graph, required
feature coverage, step continuity, scenario registry, technical-role registry,
or section-mirroring gate exists before delivery.

## Required regression behavior

The V7.1 artifact must fail V7.2 semantics with findings for fragmented
embodiments, prohibited semantic roles, unsupported generalization, scenario
drift, comparison-baseline promotion, and Section 5/7 mirroring. A valid V7.2
primary embodiment must instead follow one evidence-grounded implementation
path and cover every required feature while retaining validation and limitation
facts in their proper roles.
