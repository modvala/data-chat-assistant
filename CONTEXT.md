# Data Chat Assistant

A chat agent that lets the non-technical executives of a retail company ask questions about sales data and get analysis and reports.

## Language

### People

**Customer**:
A person who buys products from the retail company. One row in the `users` table is one Customer.
_Avoid_: Client, user, buyer

**Executive**:
A person who chats with the agent. An Executive is a Manager or the CEO.
_Avoid_: User, chat user

**Manager**:
An Executive who owns one or more brands and can analyze only the data of these brands.
_Avoid_: Brand owner

**CEO**:
The Executive who can analyze all data, with no brand limit. The CEO also owns the Persona.

**Project client**:
The company that ordered this project: OpsFleet. It sets the requirements and makes the decisions that the design cannot make alone.
_Avoid_: Customer, client (alone)

### Access

**Brand scope**:
The set of brands whose data an Executive can analyze. For a Manager, it is the brands that the Manager owns. For the CEO, it is all brands.
_Avoid_: Permissions, category scope

**Effective scope**:
The data that one query can read: the intersection of what the agent permits and the Brand scope of the Executive who asks.
_Avoid_: Access rights, scope (alone)

### Conversation

**Turn**:
One message from an Executive and the Answer that the agent gives to it.
_Avoid_: Request, exchange

**Answer**:
One reply of the agent in the chat.
_Avoid_: Report, response

**Provenance**:
The facts behind an Answer: the Brand scope, the assumptions, the Trios and the Metric variant that the agent used, and its SQL queries. Each Answer has its Provenance.
_Avoid_: Transparency block, metadata

**Action item**:
One recommended next step in an Answer or a Saved Report, with the metric to watch. An Action item can name an owner.
_Avoid_: Recommendation, task

**Saved Report**:
A stored analysis that an Executive asked the agent to keep. It belongs to the Executive who saved it, and it records the Customers that it mentions. Only its owner can delete it.
_Avoid_: Report (alone), answer

**Undo window**:
The time after a delete in which the Executive can restore the deleted Saved Reports.
_Avoid_: Grace period

**Persona**:
The organization-wide tone and the content rules for all Answers. The CEO changes it, and it has versions.
_Avoid_: Prompt, instructions, style

**Executive profile**:
The presentation preferences of one Executive, such as format, depth and length. It holds learned values and explicit edits by the Executive. An explicit edit wins over a learned value.
_Avoid_: Preferences (alone), user memory

### Knowledge

**Trio**:
One example of expert work: a question, the SQL query that answers it, and the analyst report about the result.
_Avoid_: Example, sample

**Golden Bucket**:
The collection of approved Trios that the agent uses to interpret new questions as analysts did before.
_Avoid_: Knowledge base, examples store

**Trio retrieval**:
Finding the Trios that are close in meaning to a new question.
_Avoid_: Semantic search, RAG

**Metric catalog**:
The reviewed definitions of business metrics, such as churn and spend, with their synonyms. The industry name is "semantic layer".
_Avoid_: Semantic layer, ontology, dictionary

**Metric variant**:
One named definition of a metric in the Metric catalog, for example churn after 60 days or after 90 days without an order. One variant of each metric is the organization default.
_Avoid_: Personal definition, custom metric
