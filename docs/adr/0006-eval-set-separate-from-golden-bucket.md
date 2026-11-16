# The eval set is separate from the Golden Bucket

Scope: both

Trios are never eval cases. When the agent retrieves a Trio that is also the eval question, it finds the correct answer by retrieval, and the score is not honest. So the eval set is a separate hold-out set. The prototype target is 5 questions with reference SQL (AC-R6.1, a Bonus that is not done). Production has a larger set behind the CI eval gate. Red-team cases are pytest tests (P23), not part of the eval set.

## Considered options

- **A Trio is also an eval case, with leave-one-out retrieval**: reuses data, but it adds logic and it is easy to break. Rejected.
