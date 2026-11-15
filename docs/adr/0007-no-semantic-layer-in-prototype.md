# The prototype has no semantic layer; Trios carry the interpretation

Scope: prototype

The dataset has no definition of terms such as "churn" or "underspending", and fixed definitions are complex to agree on. So the prototype has no semantic layer. The interpretation of such a question lives in the Trio itself: its SQL and its report show how an analyst understood it. This is the purpose of R1. The prototype retrieves Trios only by embeddings, with no ontology tags.

The design keeps P12: the semantic layer is the production target. Definitions for each Executive (for example, "for me, churn means 60 days") are further development, as part of the Executive profile.
