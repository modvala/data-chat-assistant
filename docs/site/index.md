# Data Chat Assistant

**Status:** all 13 required acceptance criteria work in the prototype. The planned extras and the production design are only in the design documents.

The Data Chat Assistant is a terminal chat for the Executives of a retail company: the brand managers and the CEO. An Executive asks a question about the sales data in plain words. The agent gives an Answer (a reply with analysis) in the chat.

## See an Answer

An Executive asks for a report:

```text
Create a report for the last quarter with insights and action items for the next quarter
```

The Answer has this shape:

```text
╭─ ◆ Sales report, <quarter> ──────────────────────────────────╮
│ Revenue $n ▲ n%    Orders n ▲ n%    Customers n ▼ n%         │
│ <quarter> vs <previous quarter>                              │
│                                                              │
│ <Two or three sentences with the main findings.>             │
│                                                              │
│ Action items                                                 │
│  1. <A verb and the action for the next quarter>             │
│     Watch: <metric>                                          │
│  2. <A verb and the action for the next quarter>             │
│     Watch: <metric>                                          │
╰──────────────────────────────────────────────────────────────╯
  Scope: <brands> · trace <id> · /sql · /save
  Assumed: "last quarter" = <quarter>
```

The Answer starts with the key figures. It ends with Action items: the recommended next steps, each with a metric to watch. The line under the Answer shows the brands, the trace ID and the commands for the SQL and for a save. The figures come from the query results, not from the text of the language model.

**Details:** [CLI design: Answer model](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/cli.md#answer-model) · [C7 KPI row](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/cli.md#c7-kpi-row) · [C10 Provenance line](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/cli.md#c10-provenance-line)

## What it does

<div class="grid cards" markdown>

- **Ask in plain words.** The agent writes the SQL for each question, runs it and explains the result. [How it works](how-it-works.md)
- **Only your brands' data.** Each query reads only the data of your brands, and the agent never shows personal data. [Requirements, R2](requirements.md#r2-safety-and-pii-masking-only-your-brands-data)
- **Nothing is deleted without your yes.** Your saved reports (the analyses that you keep) are deleted only after you type the exact reply. You can undo the delete. [Requirements, R3](requirements.md#r3-high-stakes-oversight-nothing-is-deleted-without-your-yes)
- **Each Answer shows its sources.** Each Answer shows the brands, the assumptions and a trace ID, and you can see each step. [Requirements, R7](requirements.md#r7-observability-each-answer-shows-its-sources)

</div>

**Details:** [HLD §1 Purpose](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/hld.md#1-purpose) · [HLD §2.1 Functional requirements](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/hld.md#21-functional-requirements)

## Project status

Each requirement has acceptance criteria: the checks that show that the requirement is done. This table counts them for each label.

| Label | Core chat and R1–R8 | Extras |
| --- | --- | --- |
| **Works in the prototype** | 13 | 0 |
| **Planned extra** | 5 | 2 |
| **Production design** | 7 | 2 |

The [Requirements](requirements.md) page gives each acceptance criterion and its label.

**Details:** [Requirements coverage](https://github.com/modvala/data-chat-assistant/blob/main/docs/requirements-coverage.md)

## Start here

- **Reviewer:** read [How it works](how-it-works.md).
- **Engineer:** install and run the prototype with the [setup steps](get-started.md).
- **Executive:** learn how to ask and read Answers in the [Executive guide](guide.md).
