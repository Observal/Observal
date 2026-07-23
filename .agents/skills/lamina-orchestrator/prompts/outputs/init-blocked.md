# Output contract: init blocked

Emit this contract when the init-required gate fails. **Copy this block exactly** — do not emit design or audit output contracts. Do not substitute a prose-only refusal.

**Required:** All five headings below must appear in your response.

```markdown
## Lamina: init required

### Status
Blocked — `/lamina-init` has not been run on this project, or `.lamina/business-context.md` is incomplete.

### What's missing
- <specific validation failure>
- <another failure if applicable>

### Next step
Run `/lamina-init` to establish `.lamina/business-context.md`, then retry this command.

### Do not
- Proceed with workflow steps or create `.lamina/` artifacts
- Auto-run init without the user invoking `/lamina-init`
- Treat personas or prior product graphs as a substitute for business context
```

Keep **What's missing** concrete — cite the exact failed checks (missing file, empty file, missing section name, placeholder answer, invalid frontmatter field, personas offered as init substitute).
