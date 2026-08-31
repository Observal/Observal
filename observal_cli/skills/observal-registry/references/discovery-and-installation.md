<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Discovery and installation

## Contents

- Search and inspect
- Personalized recommendations
- Install components
- Verification

## Search and inspect

Start broad with natural-language search, then narrow only when needed.

```bash
observal registry mcp list --search 'github docker' --output json
observal registry mcp list --category developer-tools --output json
observal registry skill list --search 'frontend design' --harness claude-code --output json
observal registry skill list --team platform-tools --output json
observal registry hook list --event UserPromptSubmit --output json
observal registry prompt list --category code-generation --output json
observal registry sandbox list --runtime docker --output json
observal registry models --harness kiro --output json
```

Summarize matches by `qualified_name`, description, version, supported harnesses, and why they match the request. If no result appears, retry once with fewer keywords.

Inspect a selected component with its canonical identity:

```bash
observal registry mcp show NAMESPACE/SLUG --output json
observal registry skill show NAMESPACE/SLUG --output json
observal registry hook show NAMESPACE/SLUG --output json
observal registry prompt show NAMESPACE/SLUG --output json
observal registry sandbox show NAMESPACE/SLUG --output json
```

## Personalized recommendations

Use recommendations for open-ended requests such as "what should I install?" or "what am I missing?"

```bash
observal registry recommend --output json
observal registry recommend --limit 12 --type mcp --refresh --output json
```

Interpret fields precisely:

- `personalized: true`: ranked from this user's sessions.
- `personalized: false`: popularity fallback because no usable personal profile exists.
- Low `profile_sessions`: answer, but say evidence is thin.
- Empty `items`: successful result, not an error.
- `items[].reason`: quote or summarize this reason without inventing another.

Dismiss only after user confirmation because the preference is durable:

```bash
observal registry recommend dismiss skill NAMESPACE/SLUG --action not_relevant --output json
```

## Install components

Choose the exact harness and scope before writing files.

```bash
observal registry mcp install NAMESPACE/SLUG --harness kiro --no-prompt --output json
observal registry mcp install NAMESPACE/SLUG --harness cursor --version 2.1.0 --no-prompt --output json
observal registry skill install NAMESPACE/SLUG --harness claude-code --scope project --output json
observal registry skill install NAMESPACE/SLUG --harness kiro --scope user --version 1.2.0 --output json
observal registry hook install NAMESPACE/SLUG --harness kiro --output json
observal registry hook install NAMESPACE/SLUG --harness claude-code --platform darwin --dir . --output json
```

Use raw output only when the user explicitly asks for a config snippet or raw response:

```bash
observal registry mcp install NAMESPACE/SLUG --harness claude-code --raw
```

Never combine raw and JSON modes. Never print supplied environment or header values.

## Verification

Inspect returned files, setup instructions, warnings, and version. For harness writes, verify with:

```bash
observal scan --harness kiro --output json
```

If installation reports a failed setup command or file write, report partial failure rather than success.
