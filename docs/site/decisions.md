# Key decisions

**Status:** the prototype follows the decisions on safety, deletes, the agent framework and the language models. The cloud, search, test and tone decisions are production design only.

This page gives each key decision of the design: what we chose, what we did not choose, and why. A decision that is hard to change has an architecture decision record (ADR).

**Details:** [HLD §24 Key decisions](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/hld.md#24-key-decisions)

Words on this page:

- An Executive is a person who chats with the agent: a brand manager or the CEO.
- A Turn is one question of an Executive and the Answer (the reply of the agent) to it.
- The Brand scope is the set of brands whose data an Executive can see.
- A Saved Report is an analysis that an Executive keeps. A Customer is a person who buys from the company.
- A Trio is a question, its SQL and the analyst report. The Golden Bucket is the set of approved Trios.
- The Metric catalog is the set of reviewed definitions of business metrics, such as churn.
- The Executive profile keeps the preferred format of one Executive. The Persona is the tone and the content rules that the CEO sets.

## Safety and access

- **Brand scope:** We chose to apply the Brand scope in our code and again in BigQuery in production, not in only one place. Two layers cost more work, but one bug cannot leak data. **Details:** [ADR 0001](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0001-brand-scope-by-view-rewrite.md)
- **Delete safety:** We chose a language model that only plans a delete, not a delete tool with a framework confirmation. Our code checks the reply: it is more code, but no prompt can make the model delete. **Details:** [ADR 0002](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0002-llm-has-no-delete-tool.md)
- **Delete reply:** We chose a short reply that gets stricter when more Saved Reports match, not a random confirmation code. The reply is easy to type, and an internal link to the exact reports gives the safety. **Details:** [ADR 0002](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0002-llm-has-no-delete-tool.md)
- **Small groups:** We chose to hide small groups only in results by age, gender or place, not in all data or by our filter only. A list of top Customers still works, and our code decides which queries need it. **Details:** [ADR 0005](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0005-aggregation-threshold-on-demographic-path.md)
- **Input check:** We chose rules, a low-cost language model check and managed screening, not managed screening only or a model check only. More than one layer is safer, and the model check also finds the type of the request.
- **Output check:** We chose rules and a managed check for personal data, not rules only. The managed check finds more types of personal data, for a small cost for each Answer.
- **Access mapping:** We chose one BigQuery table with the brands of each Executive, not a configuration file or a copy in Firestore. Our code and the BigQuery access rules then use one source.

## Platform

- **Agent framework:** We chose Google ADK with all safety code outside it, not LangGraph, a plain Gemini library loop first, or PydanticAI inside ADK. ADK fits Google Cloud and has callbacks for our checks, but the team is new to it, so our core stays free of it. **Details:** [ADR 0003](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0003-google-adk-framework.md)
- **Compute and state:** We chose Cloud Run and Firestore, not the managed agent runtime of Google Cloud with its sessions and memory. It is more code, but the state is structured, editable and in our own store, with less lock-in. **Details:** [ADR 0004](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0004-cloud-run-and-firestore.md)
- **Production channel:** We chose the terminal chat through Identity-Aware Proxy, not a web chat. It needs no new front end, and a web chat can use the same agent service later.
- **Turn transport:** We chose HTTPS with server-sent events, not WebSocket or polling. It is simple, it works through Identity-Aware Proxy, and one direction is sufficient.
- **Other clouds:** We chose Google Cloud now, with a design that permits a move, not AWS, Azure or our own servers. The data and the preferred language model are on Google Cloud, and a new warehouse needs its own row-level security.

## AI and knowledge

- **Main language model:** We chose a fast Gemini model, and a smaller one for backup and input checks, not the largest model for all Turns. The cost and the wait are low, and a larger model for long reports is a later option.
- **Metrics in the prototype:** We chose no Metric catalog in the prototype, where Trios carry the meaning of terms, not a small catalog file. It is less work now, and the catalog is the production target. **Details:** [ADR 0007](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0007-no-metric-catalog-in-prototype.md)
- **Vector search:** We chose an exact vector search in BigQuery while the Golden Bucket is small, not Vertex AI Vector Search or a vector database. It needs fewer services, but it is slower than a dedicated index at a large scale.
- **Eval data:** We chose a set of test questions that is separate from the Golden Bucket, not Trios that are also test questions. It is more data to keep, but the score is honest. **Details:** [ADR 0006](https://github.com/modvala/data-chat-assistant/blob/main/docs/adr/0006-eval-set-separate-from-golden-bucket.md)
- **Profile update:** We chose a job after each Turn to update the Executive profile, not an update inside the Turn. The Turn stays fast, and the profile is only one Turn late.

## Operations

- **Observability:** We chose Cloud Trace and masked logs with a copy in BigQuery, not a self-hosted trace tool or trace sinks. There is no extra service to operate, and a saved query and `/trace` show the dialog.
- **Persona editing:** We chose a form with versions of the Persona, not a file in Git with a pull request or a shared document. A person who is not a developer can then edit it with checks, a preview and a rollback.
