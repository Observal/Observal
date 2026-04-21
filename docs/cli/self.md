# observal self

Manage the CLI itself — upgrades and downgrades.

## Subcommands

| Command | Description |
| --- | --- |
| [`self upgrade`](#observal-self-upgrade) | Upgrade to the latest CLI version |
| [`self downgrade`](#observal-self-downgrade) | Downgrade to the previously installed version |

---

## `observal self upgrade`

Upgrade to the latest version of `observal-cli` from PyPI. The command auto-detects whether you installed with `uv`, `pipx`, or `pip` and routes through the right tool.

```bash
observal self upgrade
```

Output:

```
Detected installer: uv tool
Current version:    0.8.3
Latest version:     0.9.1
Upgrading...
Done. observal is now 0.9.1.
```

After an upgrade, restart any long-running IDE sessions so they pick up the newer shim binary.

---

## `observal self downgrade`

Revert to the version you had installed before the most recent `self upgrade`.

```bash
observal self downgrade
```

This records the previous version when upgrading, so downgrade is exact — not "one minor version back."

## When to use this

* A new release introduced a regression and you need to roll back fast.
* You're on a long-running install and `uv tool upgrade observal-cli` / `pipx upgrade` is simpler for you to type.

## Related

* [Installation](../getting-started/installation.md) — the full install guide
