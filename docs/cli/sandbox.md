<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Sandbox Registry

The `sandbox` command group allows you to manage sandbox environments within the Observal registry. Use these commands to submit, list, and configure environments for AI agent testing.

## Usage

```bash
observal registry sandbox [OPTIONS] COMMAND [ARGS]...
```

## Commands

### submit
Submit a new sandbox environment for review.
```bash
observal registry sandbox submit [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

**Example:**
```bash
observal registry sandbox submit --path ./my-env
```

---

### list
List approved sandboxes in the registry.
```bash
observal registry sandbox list [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

**Example:**
```bash
observal registry sandbox list
```

---

### show
Show detailed information about a specific sandbox.
```bash
observal registry sandbox show [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

**Example:**
```bash
observal registry sandbox show python-web-container
```

---

### install
Generate IDE install configuration for a sandbox.
```bash
observal registry sandbox install [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

**Example:**
```bash
observal registry sandbox install --ide cursor
```

---

### edit
Edit a draft, rejected, or pending sandbox submission.
```bash
observal registry sandbox edit [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

---

### delete
Delete a sandbox from the registry.
```bash
observal registry sandbox delete [OPTIONS]
```
**Options:**
| Flag | Description |
| --- | --- |
| `--help` | Show this message and exit. |

**Example:**
```bash
observal registry sandbox delete old-test-env
```
```

---

### Mentor Check 🔍
Before we move to the terminal to save this forever:
1. **Did you also update `docs/SUMMARY.md`?** (You should add `* [sandbox](cli/sandbox.md)` under the CLI section).
2. **Did you update `docs/cli/README.md`?** (Add a link to the new sandbox page in the list of commands).

**Once those three files are saved, let me know and we will run the final Git commands to push your second contribution!** You are doing a fantastic job providing value to the community. 🌟📖