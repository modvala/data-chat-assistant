# The prototype has no Metric catalog; Trios carry the interpretation

Scope: prototype

The dataset has no definition of terms such as "churn" or "underspending", and fixed definitions are complex to agree on. So the prototype has no Metric catalog. The interpretation of such a question lives in the Trio itself: its SQL and its report show how an analyst understood it. This is the purpose of R1. In the prototype, Trio retrieval uses only embeddings, with no metric tags.

The design keeps P12: the Metric catalog is the production target. In production, the Metric catalog can hold more than one Metric variant of a metric, for example `churn_90d` and `churn_60d`. One variant is the organization default. An Executive who wants a different variant names it in the question. Each Answer names the variant that it used (P22).

We do not keep metric definitions for each Executive, and the Executive profile holds no default variant. If each Executive had their own meaning of "churn", two Executives could ask the same question, get different numbers and not see why.

A larger option for later is to grow the Metric catalog into an ontology. An ontology also describes the business entities, such as Customer, Order, Product and Brand, and the relations between them. A tool can make a first draft of it from the schema, the data and the query history, and analysts then certify each definition. [NVIDIA Auto Ontology](https://github.com/NVIDIA/auto-ontology) is one example, but in November 2026 it does not support BigQuery. The assignment has only four tables, so a hand-written Metric catalog is sufficient for now. An ontology becomes useful when the agent must use many tables or many systems.
