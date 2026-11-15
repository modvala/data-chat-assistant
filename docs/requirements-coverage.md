# Requirements coverage

This page maps each requirement of the [technical assignment](requirements/2026-11-12-client-technical-assignment.md) to its acceptance criteria (AC), the design section, the code, the test and the demo scenario (P25). Requirements R1–R8 are Requirements 1–8 of the assignment.

## How to read this page

| Mark | Meaning | Proof |
| --- | --- | --- |
| **Must** | The prototype must have it (P1). | An automated test and a demo scenario. |
| **Bonus** | Code only after all Must ACs pass (P2). | A test or a demo scenario. |
| **Design** | Only in the design documents. | A design section. There is no code. |

The Design, Code, Test and Demo columns stay empty ("—") until the work exists.

## Core chat (P1)

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-CORE.1 | The CLI agent makes BigQuery SQL at run time, keeps the conversation context and builds a report with action items when the Executive asks. | **Must** | — | — | — | — |

## R1. Hybrid Intelligence

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R1.1 | At query time, the agent retrieves the top-k similar Trios and puts them into the context. The Answer shows the IDs of the Trios that it used (P22). The prototype retrieves by embeddings only (ADR 0007). Production also filters by ontology tags. | Bonus | — | — | — | — |
| AC-R1.2 | The design shows the update loop: candidate → analyst review → tag → index (P13), with versions for Trios and a retirement of old Trios. | Design | — | — | — | — |
| AC-R1.3 | The prototype has 2–3 Trios, made from the example questions of the assignment, and cites them in Answers. | Bonus | — | — | — | — |

## R2. Safety & PII Masking

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R2.1 | No PII column gets to the LLM or to the output. The validator works on the SQL AST, so it also catches `SELECT *`, aliases and expressions. A scan of the output is the last layer. All red-team cases are blocked. | **Must** | — | — | — | — |
| AC-R2.2 | Each query reads only the Effective scope, through the scoped views (ADR 0001). For a Manager, the figure of the agent equals the figure of a reference query on the brands of that Manager. A request to go out of the scope gets a refusal. | **Must** | — | — | — | — |
| AC-R2.3 | A request that is not analysis (prompt injection, a request for the system prompt, a poem) gets a polite refusal. A demographic query goes to the threshold view with k = 5, or gets `HAVING COUNT(DISTINCT user_id) >= 5` as the fallback (ADR 0005). | **Must** | — | — | — | — |

## R3. High-Stakes Oversight

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R3.1 | A delete request shows a preview (the count and the titles of the matched Saved Reports) and a confirmation code. Nothing changes before the Executive types the code. Any other message cancels the request, and the code expires after its TTL. The LLM has no delete tool (ADR 0002). The friction grows with the blast radius: "yes" for 1 report, the count (for example `delete 7`) for more than 3 reports. | **Must** | — | — | — | — |
| AC-R3.2 | An Executive can delete only the Saved Reports that they own. The code is bound to the Executive, the session and the hash of the exact set of report IDs. "Reports mentioning Customer X" matches on the Customer IDs that each Saved Report records. For a name, the agent asks for the Customer ID. | **Must** | — | — | — | — |
| AC-R3.3 | The delete is soft and writes an audit log entry. The `undo` command restores the reports during an undo window. | **Must** | — | — | — | — |

## R4. Continuous Improvement (Learning Loop)

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R4.1 | User level: the Executive profile learns format, depth and length from explicit requests and from implicit signals, with a confidence and a decay. The Executive can see and edit the profile. An explicit edit wins over a learned value. | Design | — | — | — | — |
| AC-R4.2 | System level: signals (feedback, rephrased questions, SQL corrections, failed turns) become candidate Trios and candidate changes. An eval gate checks each change before release. The system never changes itself without the gate. | Design | — | — | — | — |
| AC-R4.3 | The prototype keeps a YAML Executive profile for each Executive, shows and edits it with `/profile`, and uses it in the next session. | Bonus | — | — | — | — |

## R5. Resilience & Graceful Error Handling

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R5.1 | For a SQL error, the agent first does a dry run, then makes not more than 2 correction attempts. For an empty result, it runs a diagnostic query on the distinct values of the filter column and gives an honest Answer. The CLI does not stop. | **Must** | — | — | — | — |
| AC-R5.2 | For 429, 5xx or a timeout from the LLM or BigQuery, the agent uses backoff, then the fallback model, then a friendly message with the `trace_id`. The session continues. Chaos mode (`CHAOS=llm_429:0.3,bq_timeout:0.1`) proves this. | **Must** | — | — | — | — |
| AC-R5.3 | Each turn has a budget for LLM calls, tokens, bytes scanned and wall time. When a turn goes over the budget, the agent stops and explains why. | **Must** | — | — | — | — |

## R6. Quality Assurance

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R6.1 | An eval set of 5 questions with reference SQL, separate from the Golden Bucket (ADR 0006), measures execution accuracy. CI runs it and publishes the report to the Pages site. | Bonus | — | — | — | — |
| AC-R6.2 | An LLM judge checks intent with a rubric (does the Answer reply to the question, are the action items specific), calibrated against a small set of human labels. | Design (optional) | — | — | — | — |
| AC-R6.3 | UX eval: a pairwise preference test, in which the Executive sees two Answer variants and selects the better one. | Design | — | — | — | — |

## R7. Observability

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R7.1 | The CLI shows the `trace_id` of each turn. The trace has spans for LLM calls (model, tokens, latency), tools (SQL, bytes, rows) and guardrail decisions (block reason). No PII goes into a trace. | **Must** | — | — | — | — |
| AC-R7.2 | The docs define the metrics before the code: turn success rate, block rate for each reason, self-correction rate, empty-result rate, LLM error and fallback rate, p50/p95 latency, cost for each turn, and the completion and abort rate of confirmations. Each metric comes out as a span attribute or a log field. | **Must** | — | — | — | — |
| AC-R7.3 | The `/trace <id>` command shows the full dialog again, step by step, from the JSONL trace file. | **Must** | — | — | — | — |

## R8. Agility (Persona Management)

| ID | Acceptance criterion | Mark | Design | Code | Test | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R8.1 | The Persona is outside the code, has versions and a non-developer can edit it. The system reads it again on each turn, so a change needs no deployment. | Design | — | — | — | — |
| AC-R8.2 | Before a Persona change goes live, the system validates it, shows a sample Answer in the new tone and permits a rollback. Each trace records the Persona version. | Design | — | — | — | — |
| AC-R8.3 | The prototype reads `persona.yaml` on each turn. The prompt has layers: the safety layer is locked, and only the tone layer comes from the Persona. | Bonus | — | — | — | — |

The prompt has three layers. An upper layer wins on its own topic:

```mermaid
flowchart TB
    S["Safety layer<br/>locked, only developers change it"] --> P["Persona<br/>tone and must-have content, the CEO edits it"]
    P --> E["Executive profile<br/>format, depth and length"]
    E --> A[Context of the Answer]
```

## Extras

| ID | Item | Mark |
| --- | --- | --- |
| EX.1 | A result cache keyed by a hash of the normalized SQL | Bonus |
| EX.2 | Trace export to Langfuse Cloud | Bonus |
| EX.3 | A circuit breaker for each external service | Design |
| EX.4 | Production observability: Cloud Trace, Logging and Monitoring, plus self-hosted Langfuse on Cloud Run | Design |
