<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Self-Learning Loop

> Scoped out of PR #1023. To be shipped as a separate PR once the key generation tooling and pipeline are complete.

## What it does

After every session ends, the agent automatically improves from that production usage. No manual curation, no waiting for a full insight report.

## The 5-step loop

```
Session ends (final=True on ingest)
        │
        ▼
1. Build transcript
   session_cache.py pulls the session's JSONL events from ClickHouse
   and assembles a plain-text conversation log

        │
        ▼
2. Extract facets  (~$0.005 per session, one LLM call)
   facets.py sends the transcript to the configured LLM and pulls out
   behavioral signals: tool preferences, user corrections, friction
   points, what worked well

        │
        ▼
3. Accumulate facets
   Facets are stored in the DB and merged with all previous sessions
   for that agent

        │
        ▼
4. Synthesize learned skill
   skill_synthesis.py formats the accumulated facets into a markdown
   rules block and stores it as a learned_skill row in the DB

        │
        ▼
5. Inject at next session start
   session_start_learning.py (CLI hook) fetches the latest active
   learned skill and prepends it to the agent's system prompt
```

## Key distinction from the insight pipeline

Insights (`generate_insight_report`) is a **periodic batch report** — runs on a cron schedule (weekly), reads many sessions, produces a narrative HTML report for maintainers to read.

Self-learning is a **per-session incremental update** — fires after every single session, cheap, invisible to the user, feeds directly back into the agent's behaviour at the next session start.

## Files (all removed from PR #1023)

| File                                                         | Purpose                                                                        |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| `ee/observal_insights/post_session_learning.py`              | Orchestrates steps 1-4 as a background task                                    |
| `ee/observal_insights/session_cache.py`                      | Builds transcript from ClickHouse session events                               |
| `ee/observal_insights/skill_synthesis.py`                    | Converts accumulated facets into agent rules markdown                          |
| `ee/observal_insights/skill_validation.py`                   | Validates synthesized skill before storing                                     |
| `ee/observal_server/routes/learned_skills.py`                | API routes: GET /learned-skills, PUT /self-learning toggle                     |
| `observal-server/api/routes/learned_skills.py`               | Open-source stub (returns 403 without license)                                 |
| `observal-server/models/learned_skill.py`                    | DB model: id, agent_id, name, content, source, status                          |
| `observal-server/alembic/versions/0007_add_self_learning.py` | Migration: self_learning_enabled/min_sessions on agents + learned_skills table |
| `observal_cli/hooks/session_start_learning.py`               | SessionStart hook: fetches latest rules and injects into prompt                |
| `web/src/components/registry/self-learning-tab.tsx`          | Frontend tab: toggle, rule list, synthesize button                             |
| `tests/test_self_learning.py`                                | Integration tests for the full loop                                            |

## What still needs to be done before shipping

1. **Key generation tooling** — no script exists to generate the Ed25519 keypair or sign license payloads. The license gate (PR #1023) must ship and the private key must be generated before self-learning can be tested end-to-end.
2. **LLM config** — requires `INSIGHT_MODEL_FACETS` to be set to a real model endpoint. Currently only Bedrock is wired up.
3. **`retroactive_learning`** — `trigger_retroactive_learning` (called when self-learning is toggled ON for an agent with existing sessions) was in the codebase but incomplete.
4. **Rate limiting** — no throttle on the per-session LLM call. High-traffic agents could rack up significant cost.
