Use these exact headings when a Lamina command must ask blocking clarifying questions before artifact generation. Do not write `.lamina/` files when using this contract.

```markdown
## Lamina: clarification needed
### Status
Blocked before artifact generation.
### Clarifying questions
One concise batch of the specific answers needed to proceed.
### Why these block the artifact
Briefly name which artifact or workflow step would become speculative without the answer.
### How to proceed
Ask the user to answer the questions, or explicitly say they want to proceed with unanswered items preserved as Open questions and labeled assumptions where allowed.
### Do not
- Do not create `run.json`, `report.md`, personas, findings, implementation contracts, or walkthrough files yet.
- Do not resolve the unknowns with hidden assumptions.
```
