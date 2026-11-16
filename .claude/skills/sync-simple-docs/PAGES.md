# Page specs

The spec of each page of `docs/site/`. The nav in `mkdocs.yml` has the same order.

| Nav group | Page | File | Kind |
| --- | --- | --- | --- |
| — | Home | `index.md` | derived |
| Understand | How it works | `how-it-works.md` | derived |
| Understand | Requirements | `requirements.md` | derived |
| Understand | Key decisions | `decisions.md` | derived |
| Try it | Get started | `get-started.md` | source |
| Try it | Demo tour | `demo-tour.md` | source |
| Use it | Executive guide | `guide.md` | source |

## Source map

Use this map in step 1 to find the pages that a changed file affects.

| Changed file | Pages |
| --- | --- |
| `docs/design/hld.md` | Home, How it works, Requirements, Key decisions |
| `docs/adr/*` | Key decisions, Requirements |
| `docs/requirements-coverage.md` | Home, Requirements, Demo tour |
| `docs/requirements/*` | Requirements |
| `docs/design/cli.md` | Home, Executive guide |
| `docs/tech-stack.md` | How it works |
| `pyproject.toml`, `.env.example`, `scripts/*`, `executives.json` | Get started, Executive guide |
| `src/dca/cli/*` | Executive guide, Demo tour, Get started |
| `src/dca/setup_bq.py`, `compose.yaml`, `docker/*`, `config/defaults.toml`, `tests/test_live.py` | Get started |
| `src/dca/core/messages.py`, `src/dca/app/turn_api.py` | Executive guide, Demo tour |

## Home (`index.md`)

**Reader:** all three readers. **Sources:** `docs/design/hld.md` (§1, §4.1), `docs/requirements-coverage.md`, `docs/design/cli.md` (Answer model, C5, C7, C9, C10).

**Out:** the architecture, the decisions and the setup steps. Link to their pages.

Outline:

1. One to three sentences: what the product is and for whom.
2. A short example: the question in its own `text` block, then the Answer in a second `text` block, in the CLI layout of `cli.md`: a KPI row, Action items and the provenance line. Use placeholders such as `▲ n%` and `<brands>`, not data.
3. Four cards, each with one sentence and a relative link to the page that explains it:
   - "Ask in plain words" → How it works
   - "Only your brands' data" → Requirements, R2
   - "Nothing is deleted without your yes" → Requirements, R3
   - "Each Answer shows its sources" → Requirements, R7
4. Project status: a table with one row for each label and two count columns: "Core chat and R1–R8" and "Extras". Count the rows of the coverage table.
5. Start here: one line for each reader, with a relative link. Reviewer → How it works. Engineer → Get started. Executive → Executive guide.

## How it works (`how-it-works.md`)

**Reader:** reviewers and engineers. **Sources:** `docs/design/hld.md` §4.1, §6.1, §8.1, §18, §19; `docs/tech-stack.md`. Page type: an architecture doc.

**Out:** ports, code layers, the SQL rules, the Turn API, the progress events and all values (limits, budgets, model IDs).

Outline: four diagrams. Each one has a section with a sentence before the diagram, two to four sentences after it, and a Details line.

1. **Context:** the Executive, the CLI, the agent, the language model, the sales warehouse and the stores. Show which parts the Executive talks to and which parts hold data.
2. **Building blocks:** two headed sections, "In the prototype" (HLD §19) and "In production on Google Cloud" (HLD §18). One diagram each. Name the main services in production and the local files in the prototype, in groups. Mark each part that has no code on `main` (see the Facts rules).
3. **One Turn:** about 6 steps from the question to the Answer (HLD §6.1, main path), in plain words: check the message, find similar past analyses, write SQL, check and limit the SQL, run it, check the Answer. Mark a step that has no code on `main`.
4. **Safety layers:** input check → SQL check → Brand scope → output check (HLD §8.1). Say that each layer works alone, so one failure does not leak data.

## Requirements (`requirements.md`)

**Reader:** reviewers. **Sources:** `docs/requirements-coverage.md`, `docs/requirements/2026-11-12-client-technical-assignment.md`, the HLD sections that the coverage table links to.

**Out:** the Code and Test columns of the coverage table, and the values in the AC text (write what happens, not the number).

Outline: a short intro with the three labels and what they mean. Then one section for Core chat and for each of R1–R8, in this template:

````text
## R3. High-Stakes Oversight: Nothing is deleted without your yes

**The problem:** one sentence that says the customer need from the assignment again in STE.

**How we solve it:** two to four plain sentences.

(A small Mermaid diagram, only for R3 the delete flow, R5 the fallback chain of the language model and R8 the prompt layers.)

| What you get | Label |
| --- | --- |
| <AC in plain words> | **Works in the prototype** |

**See it:** [D5](demo-tour.md#d5-delete-with-a-strict-confirmation-ac-r31) · [D6](...) · **Details:** [HLD §10](https://github.com/...)
````

- In the heading, use the requirement ID and its name from the coverage table, with `and` in place of `&`, then a colon and a short plain-words tagline.
- One table row for each AC of the requirement, in the order of the coverage table, with its label.
- "See it" links to the Demo tour scenario of each Must AC, with the scenario ID (D1, D2 ...) as the link text. A requirement with no Must AC has no "See it" link.
- The page ends with an "Extras" section: one table row for each EX.* item, with its label.

## Key decisions (`decisions.md`)

**Reader:** reviewers and engineers. **Sources:** `docs/design/hld.md` §24, `docs/adr/*`.

**Out:** the full trade-off text and the consequences of the ADRs. Link to them.

Outline: a short intro, then all decisions of HLD §24 in four groups. Each decision is in exactly one group:

- **Safety and access:** who sees which data, PII, deletes and the guards.
- **Platform:** the framework, compute, state, channel, transport and cloud.
- **AI and knowledge:** the models, retrieval, metrics, evaluation and learning.
- **Operations:** observability and changes that people make at run time, such as the Persona.

The page intro has one Details link to HLD §24, and a short "Words on this page" list that explains the glossary terms of the page. Each decision is one list item with two sentences: `**<Decision>:** We chose X, not Y. <Z>.` Take X from the Choice column, Y from Alternatives and Z (the reason, in plain words) from Trade-off. A decision with an ADR ends with a Details link to the ADR on github.com. The groups have no Details line. Each item agrees with HLD §24 and with its ADR. When they do not agree, write what the ADR says and report it.

## Get started (`get-started.md`)

**Reader:** a reviewer or an engineer who runs the prototype. An Executive does not install anything. **Sources:** `pyproject.toml`, `.env.example`, `scripts/setup-gcp.sh`, `src/dca/setup_bq.py`, `compose.yaml`, `docker/*`, `config/defaults.toml`, `tests/test_live.py`, the `--help` output of the commands. Page type: a quick start.

**Out:** the design, and the reasons for the tools. Link to How it works and Key decisions.

Outline, in this order: prerequisites; install with `uv sync` (uv is the only dependency manager, P19); configure `.env`; the GCP setup script and ADC impersonation of `dca-agent`; `uv run setup-bq`; the first chat; run with Docker, as a second way; the offline and `live` tests and the metrics command; configuration reference; a troubleshooting table with the usual errors.

- Each step has one line that says **why** it is necessary.
- Each command is in its own `bash` block.

## Demo tour (`demo-tour.md`)

**Reader:** reviewers. **Sources:** the Must ACs of `docs/requirements-coverage.md`, the CLI, `src/dca/core/messages.py`, `src/dca/app/turn_api.py`.

**Out:** the setup steps (link to Get started) and the design of each feature (link to Requirements).

- One scenario for each Must AC, with the headings `## D<n>. <name> (AC-<id>)`. Keep the headings, because the coverage table and the Requirements page link to their anchors.
- Each scenario has: the AC in plain words, the inputs (one input in each code block, numbered), and "What you see" with the same numbers.
- A scenario for a Bonus AC is added only when its code exists.
- Each scenario can run after the scenarios before it. When a scenario needs the state of an earlier one, such as the Saved Reports of D5, say so at its start.

## Executive guide (`guide.md`)

**Reader:** Executives. **Sources:** `docs/design/cli.md`, the `/help` output (`src/dca/cli/render.py`), `src/dca/core/messages.py` (refusal and notice texts), `src/dca/app/turn_api.py`, `executives.json`.

**Out:** the setup steps, the design and the internal names of the CLI components (C1–C17).

Sections, each with short examples that you can copy:

1. Start a session (prototype: `uv run chat --executive <id>`; production: sign-in through IAP).
2. Ask a question: suggested topics from the assignment, and follow-up questions.
3. Read an Answer: KPI rows, tables, charts, Action items, the provenance line, and why the figures come from queries and not from the LLM text.
4. When the agent says no: the refusal reasons in plain words, and what to do.
5. Reports: save, list, delete with a confirmation, and undo.
6. Your profile: only when `/profile` exists in `/help`.
7. When something fails: notices, `Ctrl+C`, and the trace ID with `/trace`.
8. Command and option reference, the same as `/help`.

Then a "For the CEO" section on how the CEO changes the Persona, with the label of AC-R8.1 (**Production design** now).
