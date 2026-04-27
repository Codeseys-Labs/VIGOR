# VIGOR Research Synthesis

This document summarizes the primary research and product sources used to design VIGOR.

## Executive Summary

VIGOR is best understood as a generalization of three converging ideas:

1. **VIGA-style executable visual reasoning**: generate a program, render it, verify discrepancies, and revise.
2. **Agentic harness design**: structure models with explicit tools, memory, evaluator roles, budgets, and trace artifacts.
3. **Meta-Harness-style outer-loop optimization**: evolve the harness around a fixed model by preserving source code, execution traces, scores, and prior candidate artifacts.

VIGOR should therefore be an artifact-centric framework, not a prompt recipe. The system of record should be editable intermediate representations, compiler/reviewer outputs, and provenance.

## VIGA

### Source Summary

The VIGA repository describes VIGA as an analysis-by-synthesis code agent for programmatic visual reconstruction. It uses an iterative loop of generating, rendering, and verifying scenes against target images. Its Generator writes and executes scene programs with tools for planning, code execution, asset retrieval, and scene queries. Its Verifier examines rendered output from multiple viewpoints, identifies visual discrepancies, and provides feedback for the next iteration. The repo says the agent maintains contextual memory with plans, code diffs, and render history, and that the loop requires no finetuning.

The VIGA arXiv abstract describes a tightly coupled **code-render-inspect loop** where symbolic programs are synthesized, projected into visual states, and inspected for discrepancies to guide iterative edits. It reports support for 2D document generation, 3D reconstruction, multi-step 3D editing, and 4D physical interaction.

### Reusable Lessons

| VIGA Pattern | VIGOR Generalization |
| --- | --- |
| Generator and Verifier roles | Separate generator, reviewer, and adjudicator roles |
| Blender/PPTX programs | Editable intermediate representations for any modality |
| Rendered scene | Observable artifact produced by compiler, renderer, simulator, or runtime |
| Multi-view visual inspection | Tool-backed observation from multiple probes or metrics |
| Sliding context memory | Trajectory memory with candidate artifacts and provenance |
| Tool servers | Domain adapters with typed capabilities |
| Max rounds and end tool | Bounded loops and explicit stop reasons |

### Constraints And Limitations

VIGA is strongest in visual domains where rendering and visual comparison are natural. It still depends on the spatial perception limits of the underlying VLM and on context-window management. Its tooling is environment-heavy: Blender, conda environments, SAM/SAM3D, optional asset generation, and GPU support may be required.

For VIGOR, the lesson is to isolate domain tooling inside adapters and keep the runtime contract stable.

### Key Sources

| Source | URL |
| --- | --- |
| VIGA GitHub repository | https://github.com/Fugtemypt123/VIGA |
| VIGA README raw | https://raw.githubusercontent.com/Fugtemypt123/VIGA/main/README.md |
| VIGA architecture doc | https://raw.githubusercontent.com/Fugtemypt123/VIGA/main/docs/architecture.md |
| VIGA paper | https://arxiv.org/abs/2601.11109 |
| VIGA project page | https://fugtemypt123.github.io/VIGA-website/ |

## Meta-Harness

### Source Summary

Meta-Harness is a framework for automated search over task-specific model harnesses. Its repository defines a harness as the code around a fixed base model that decides what to store, retrieve, and show while the model works. The arXiv abstract says Meta-Harness searches over harness code using an agentic proposer that accesses source code, scores, and execution traces of all prior candidates through a filesystem.

The repo includes a reusable framework, onboarding flow, and reference experiments for text classification and Terminal-Bench 2. The repo also points to a separate optimized Terminal-Bench 2 artifact repository.

### Reusable Lessons

| Meta-Harness Pattern | VIGOR Generalization |
| --- | --- |
| Harness as optimization target | VIGOR should optimize prompts, adapters, memory, review weights, and tool policies over time |
| Filesystem history | VIGOR run archives should preserve full candidate history and traces |
| Candidate interface | Each domain adapter should define a stable candidate contract |
| Validation before evaluation | Validate IR schema and tool availability before expensive compile/review |
| Search vs held-out split | Benchmark VIGOR adapters on search sets and reserve held-out test sets |
| Frontier tracking | Track Pareto tradeoffs such as quality, cost, editability, and safety |

Meta-Harness is especially useful for VIGOR's outer loop: improving the VIGOR harness itself, not just individual artifacts.

### Key Sources

| Source | URL |
| --- | --- |
| Meta-Harness paper | https://arxiv.org/abs/2603.28052 |
| Meta-Harness reference repo | https://github.com/stanford-iris-lab/meta-harness |
| Meta-Harness project page | https://yoonholee.com/meta-harness/ |
| Terminal-Bench 2 artifact repo | https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact |

## Claude Design And Long-Running Design Harnesses

### Source Summary

Claude Design is an Anthropic Labs product for creating designs, prototypes, slides, one-pagers, and other visual artifacts. Anthropic states that users can start from prompts, images, documents, codebases, or web captures, then refine through conversation, inline comments, direct edits, and custom sliders. The help docs emphasize that the first generation is a starting point and that the real value comes from iterating.

Anthropic's long-running app harness article is more directly architectural. It describes a generator/evaluator setup inspired by GANs for frontend design, where an evaluator scores criteria such as design quality, originality, craft, and functionality. The evaluator uses Playwright MCP to inspect the live page before producing critique. The article also notes that scores do not always improve monotonically and that middle iterations may be preferable to final iterations.

### Reusable Lessons

| Pattern | VIGOR Lesson |
| --- | --- |
| First generation as starting point | VIGOR should treat one-shot outputs as seeds |
| Inline comments and direct edits | Human feedback should enter as structured patch objectives |
| Separate evaluator | Do not rely on generator self-review for subjective quality |
| Playwright-backed review | Reviewers should interact with live artifacts, not only static screenshots |
| Non-monotonic scores | Preserve candidates and use frontier selection |
| Sprint contracts | Agree on testable acceptance criteria before building/refining |

### Key Sources

| Source | URL |
| --- | --- |
| Claude Design announcement | https://www.anthropic.com/news/claude-design-anthropic-labs |
| Claude Design help docs | https://support.claude.com/en/articles/14604416-get-started-with-claude-design |
| Long-running harness design | https://www.anthropic.com/engineering/harness-design-long-running-apps |

## TRIBE v2

### Source Summary

TRIBE v2 is a Meta AI tri-modal foundation model that predicts human brain activity in response to video, audio, and language. Meta describes a three-stage architecture: tri-modal encoding, universal integration, and brain mapping. The public demo emphasizes predicted vs actual brain activity, performance, in-silico experiments, and multimodality. The GitHub repo says predictions are for the average subject on an fsaverage5 cortical mesh.

TRIBE v2 is not an agentic review system. Public materials do not describe multi-agent critique, best-of-N artifact selection, or iterative design refinement. Its relevance to VIGOR is analogical: it demonstrates canonicalized prediction under noisy measurement and in-silico experimentation over multimodal stimuli.

### Reusable Lessons

| TRIBE v2 Pattern | VIGOR Lesson |
| --- | --- |
| Predict canonical response from noisy observations | VIGOR should report reviewer consensus, disagreement, and uncertainty |
| In-silico experimentation | Use cheap simulated/automated review before expensive human review |
| Multimodal encoding | Reviewers may integrate video, audio, text, and metadata in one score |
| Predicted vs actual comparison | VIGOR review UIs should show expected vs actual quality evidence |

### Key Sources

| Source | URL |
| --- | --- |
| TRIBE v2 demo | https://aidemos.atmeta.com/tribev2 |
| TRIBE v2 repo | https://github.com/facebookresearch/tribev2 |
| TRIBE v2 publication page | https://ai.meta.com/research/publications/a-foundation-model-of-vision-audition-and-language-for-in-silico-neuroscience/ |
| TRIBE v2 model card | https://huggingface.co/facebook/tribev2 |

## Agentic Workflow Patterns

### Evaluator-Optimizer

Anthropic's building effective agents guide defines evaluator-optimizer as one LLM call generating a response while another evaluates and provides feedback in a loop. It is effective when evaluation criteria are clear and iterative refinement provides measurable value.

VIGOR should use evaluator-optimizer where output quality can be improved through actionable review.

### Orchestrator-Workers

The same Anthropic guide defines orchestrator-workers as a central LLM dynamically breaking down tasks, delegating to worker LLMs, and synthesizing results. VIGOR should use this for complex multimodal tasks where required subtasks are not known upfront.

### ReAct

ReAct interleaves reasoning and actions so the model can collect observations from tools and update plans. VIGOR should preserve observations as trace events, not hidden context.

### Reflexion And Self-Refine

Reflexion stores failure-derived linguistic feedback in episodic memory. Self-Refine uses the same LLM to critique and revise its own output. VIGOR can use self-refinement for low-risk draft polishing, but should prefer independent reviewers for high-value or subjective domains.

### LLM-As-Judge

LLM-as-judge can scale qualitative review but suffers from biases such as position bias, verbosity bias, self-enhancement bias, and reasoning limits. VIGOR should pair LLM judges with objective validators, tool-backed inspection, pairwise comparisons, order-swapping, and human calibration.

### Best-Of-N And Search

Best-of-N treats inference as search. Generate diverse candidates, compile/review each, and select using a structured rule. VIGOR should preserve selected candidate provenance and enough rejected-candidate metadata to audit the choice.

### Key Sources

| Source | URL |
| --- | --- |
| Building effective agents | https://www.anthropic.com/engineering/building-effective-agents |
| ReAct | https://arxiv.org/abs/2210.03629 |
| Reflexion | https://arxiv.org/abs/2303.11366 |
| Self-Refine | https://arxiv.org/abs/2303.17651 |
| LLM-as-judge / Chatbot Arena | https://arxiv.org/abs/2306.05685 |
| Self-consistency | https://arxiv.org/abs/2203.11171 |
| Verifier-based selection | https://arxiv.org/abs/2110.14168 |
| AlphaCode | https://arxiv.org/abs/2203.07814 |
| W3C PROV overview | https://www.w3.org/TR/prov-overview/ |

## Research-Derived Architecture Requirements

1. VIGOR must separate generation, compilation, review, adjudication, and patching.
2. VIGOR must use editable IRs as first-class artifacts.
3. VIGOR must make compilers/renderers/simulators domain adapters, not orchestration internals.
4. VIGOR must preserve full run archives for candidates, scores, traces, and decisions.
5. VIGOR must support independent reviewer ensembles and uncertainty reporting.
6. VIGOR must keep intermediate candidates and select from a frontier, not assume the last output is best.
7. VIGOR must define benchmark/evaluation splits for each downstream domain.
8. VIGOR must allow harness-level evolution inspired by Meta-Harness.
9. VIGOR must support human-in-the-loop and automatic modes.
10. VIGOR must enforce explicit budgets, stop conditions, and escalation rules.
