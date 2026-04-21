# observal admin

Admin commands. Requires the `admin` or `super_admin` role.

## Command families

* [Settings and users](#settings-and-users)
* [Review workflow](#review-workflow)
* [Evaluation engine](#evaluation-engine)
* [Penalty and weight tuning](#penalty-and-weight-tuning)
* [Canary injection (eval integrity)](#canary-injection-eval-integrity)

---

## Settings and users

| Command | Description |
| --- | --- |
| `admin settings` | List server settings |
| `admin set <key> <value>` | Update a server setting |
| `admin users` | List all users |
| `admin reset-password <email>` | Reset a user's password (interactive or `--generate`) |
| `admin delete-user <email>` | Permanently delete a user account |

### Examples

```bash
observal admin settings
observal admin set review.require_approval true

observal admin users
observal admin reset-password alice@example.com
observal admin reset-password alice@example.com --generate   # auto-generate

observal admin delete-user abandoned@example.com
```

---

## Review workflow

| Command | Description |
| --- | --- |
| `admin review list` | List pending submissions |
| `admin review show <id>` | Show submission details |
| `admin review approve <id>` | Approve a submission |
| `admin review reject <id> --reason "..."` | Reject a submission |

### Examples

```bash
observal admin review list
observal admin review show <submission-id>
observal admin review approve <submission-id>
observal admin review reject <submission-id> --reason "env vars undocumented"
```

---

## Evaluation engine

| Command | Description |
| --- | --- |
| `admin eval run <agent-id> [--trace <id>]` | Run the full eval pipeline on agent traces |
| `admin eval scorecards <agent-id> [--version V]` | List scorecards for an agent |
| `admin eval show <scorecard-id>` | Show a scorecard with per-dimension breakdown |
| `admin eval compare <agent-id> --a V1 --b V2` | Compare two versions |
| `admin eval aggregate <agent-id> [--window N]` | Aggregate scoring stats with drift detection |

### Examples

```bash
# Score every trace for this agent
observal admin eval run code-reviewer

# Score one specific trace
observal admin eval run code-reviewer --trace <trace-id>

# Browse scorecards
observal admin eval scorecards code-reviewer
observal admin eval scorecards code-reviewer --version 2.0.0

# Compare versions
observal admin eval compare code-reviewer --a 1.0.0 --b 2.0.0

# Rolling aggregate over the last 50 scorecards
observal admin eval aggregate code-reviewer --window 50
```

See [Evaluate and compare agents](../use-cases/evaluate-agents.md) for the playbook, [Evaluation engine](../concepts/evaluation.md) for the architecture.

---

## Penalty and weight tuning

Dimensions aren't equally important for every team. Weights tune that.

| Command | Description |
| --- | --- |
| `admin weights` | View global dimension weights |
| `admin weight-set <dimension> <weight>` | Set a dimension weight (0.0–1.0) |
| `admin penalties` | View penalty catalog |
| `admin penalty-set <name> [--amount N] [--active]` | Modify a penalty |

### Examples

```bash
observal admin weights
observal admin weight-set factual_grounding 0.35

observal admin penalties
observal admin penalty-set duplicate-call --amount 5 --active
observal admin penalty-set duplicate-call --active=false   # disable without deleting
```

Weights must sum to 1.0 across all dimensions.

---

## Canary injection (eval integrity)

Canaries catch agents that parrot tokens instead of doing real work.

| Command | Description |
| --- | --- |
| `admin canaries <agent-id>` | List canary configs for an agent |
| `admin canary-add <agent-id> --type <type> --point <point>` | Add a canary config |
| `admin canary-reports <agent-id>` | Show canary detection reports |
| `admin canary-delete <canary-id>` | Delete a canary config |

### Types and points

| Type | What gets injected |
| --- | --- |
| `numeric` | A numeric token (e.g., `canary-4712`) |
| `entity` | A named entity (e.g., fake PR ID, fake file name) |
| `instruction` | A synthetic instruction the agent should ignore |

| Injection point | Where it lands |
| --- | --- |
| `tool_output` | Appended to a tool response |
| `context` | Added to the agent's prompt/context |

### Example

```bash
observal admin canary-add code-reviewer --type numeric --point tool_output
observal admin canary-reports code-reviewer
```

See [Evaluate and compare agents → Eval integrity: canaries](../use-cases/evaluate-agents.md#eval-integrity-canaries).

## Related

* [Self-Hosting → Authentication and SSO](../self-hosting/authentication.md)
* [Concepts → Evaluation engine](../concepts/evaluation.md)
