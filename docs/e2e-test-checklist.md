# E2E Test Checklist

## Test Accounts

| # | Account | Role | Purpose |
|---|---------|------|---------|
| 1 | Super Admin | `super_admin` | Creates all users |
| 2 | Admin | `admin` | Multi-user traces, archive/delete agents |
| 3 | Reviewer A | `reviewer` | Reviews components + agents via CLI |
| 4 | Reviewer B | `reviewer` | Reviews components + agents via UI |
| 5 | User A | `user` | Submits components, creates agents |
| 6 | User B | `user` | Pulls agents, tests in IDEs, leaves ratings |
| 7 | User C | `user` | Also pulls agents (verifies download count increments), verifies registry visibility |

---

## 1. Environment Setup
- [ ] `make up`
- [ ] `uv install`

## 2. Super Admin — User Management
- [ ] Log in as super admin
- [ ] Create Admin account
- [ ] Create Reviewer A account
- [ ] Create Reviewer B account
- [ ] Create User A account
- [ ] Create User B account
- [ ] Create User C account

## 3. User A — Add Components (Drafts → Submit)

### Via UI
- [ ] Log in as User A via UI
- [ ] Create MCP as draft, verify it appears in drafts
- [ ] Create Skill as draft, verify it appears in drafts
- [ ] Submit MCP draft for review
- [ ] Submit Skill draft for review

### Via CLI
- [ ] Log in as User A via CLI (`observal auth login`)
- [ ] Create Prompt as draft via CLI, verify it appears in drafts
- [ ] Create Sandbox as draft via CLI, verify it appears in drafts
- [ ] Create Hook as draft via CLI, verify it appears in drafts
- [ ] Submit Prompt draft for review via CLI
- [ ] Submit Sandbox draft for review via CLI
- [ ] Submit Hook draft for review via CLI

## 4. Reviewer A — Review Components via CLI
- [ ] Log in as Reviewer A via CLI (`observal auth login`)
- [ ] List pending submissions (`observal admin review list`)
- [ ] Approve some components via CLI (`observal admin review approve`)
- [ ] Reject some components via CLI with reasons (`observal admin review reject`)

## 5. Reviewer B — Review Components via UI
- [ ] Log in as Reviewer B via UI
- [ ] View pending submissions in review queue
- [ ] Approve some components via UI
- [ ] Reject some components via UI with reasons

## 6. User A — Check Component Review Status
- [ ] Log back in as User A
- [ ] Verify accepted components show as accepted
- [ ] Verify rejected components show as rejected
- [ ] Verify draft components still show as drafts

## 7. User A — Create Agents with Components (Drafts → Submit)

### Via UI
- [ ] Create 3 agents via UI using approved components
- [ ] Save at least 1 agent as draft first, verify it appears in drafts
- [ ] Submit agents for review

### Via CLI
- [ ] Create 3 agents via CLI (`observal agent create` / `observal agent init` + `agent add` + `agent build` + `agent publish`)
- [ ] Save at least 1 agent as draft first, verify it appears in drafts
- [ ] Submit agents for review

## 8. Reviewer A — Review Agents via CLI
- [ ] Log in as Reviewer A via CLI
- [ ] List pending agent submissions (`observal admin review list`)
- [ ] Approve some agents via CLI (`observal admin review approve`)
- [ ] Reject some agents via CLI with reasons (`observal admin review reject`)

## 9. Reviewer B — Review Agents via UI
- [ ] Log in as Reviewer B via UI
- [ ] View pending agent submissions in review queue
- [ ] Approve some agents via UI
- [ ] Reject some agents via UI with reasons

## 10. User A — Check Agent Review Status
- [ ] Log back in as User A
- [ ] Verify approved agents show as approved
- [ ] Verify rejected agents show as rejected

## 11. User B — Agent Pull & Downloads
- [ ] Log in as User B via CLI (`observal auth login`)
- [ ] Pull/install an agent via CLI (`observal pull <agent> --ide <ide>`)
- [ ] Verify download count increases (0 → 1)

## 12. User C — Agent Pull & Downloads
- [ ] Log in as User C via CLI (`observal auth login`)
- [ ] Pull/install the same agent via CLI (`observal pull <agent> --ide <ide>`)
- [ ] Verify download count increases (1 → 2)

## 13. User B — Multi-IDE Long Prompt Test
- [ ] Test a long prompt involving multiple steps and tool calls in:
  - [ ] Cursor
  - [ ] Kiro
  - [ ] Claude Code
  - [ ] Codex
  - [ ] Gemini CLI
  - [ ] Copilot
  - [ ] Open Code

## 14. User B — Self Traces
- [ ] Check that User B can see their own traces
- [ ] Verify traces appear for each IDE tested

## 15. Admin — Multi-User Traces
- [ ] Log in as Admin
- [ ] Verify admin can see traces from User B
- [ ] Verify admin can see traces from User C
- [ ] Verify admin can see traces from multiple users simultaneously

## 16. Feedback & Ratings
- [ ] As User B, leave star ratings (1-5) on agents
- [ ] As User B, leave star ratings (1-5) on components
- [ ] As User B, add comments with ratings
- [ ] As User C, leave ratings on the same agents/components
- [ ] Verify aggregate rating summary displays correctly

## 17. CLI — Scan & Doctor
- [ ] Run `observal scan` to detect IDE configs
- [ ] Run `observal self doctor` to check IDE compatibility

## 18. Admin — Agent Registry Management
- [ ] Log in as Admin
- [ ] Go to agent registry
- [ ] Archive some agents
- [ ] Delete some agents

## 19. User C — Verify Registry Visibility
- [ ] Log in as User C
- [ ] Verify archived agents are not visible in the registry
- [ ] Verify deleted agents are not visible in the registry
