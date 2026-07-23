# Fix brief

Write `fix.md` from non-ops `findings[]` in priority order.

For each finding include:

- Finding id, target, severity, and graph references.
- Concrete source or walkthrough evidence.
- Observable acceptance criteria.
- Dependencies and regressions to recheck.

Keep ops findings in `report.md`. Always create `fix.md`; write `_No product or contract findings._` only when every critical promise has independent evidence and no unresolved contract checklist remains.
