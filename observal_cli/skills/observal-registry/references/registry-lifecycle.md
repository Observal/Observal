<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Registry lifecycle

## Contents

- Read owned state
- Fork an approved component
- Edit
- Publish a version
- Archive and restore
- Transfer ownership
- Co-authors
- Error decisions

## Read owned state

Read status, version, ownership, and optimistic-lock fields before mutation.

```bash
observal registry mcp my --output json
observal registry skill my --output json
observal registry prompt my --output json
observal registry mcp show NAMESPACE/SLUG --output json
```

Use returned UUIDs or `qualified_name` values in later commands.

## Fork an approved component

When the user wants an independently owned copy rather than a new version of the original, inspect its approved status and fork once. Only approved source versions may be selected. Provide a new name and target explicitly when requested; use canonical names or UUIDs rather than bare names.

```bash
observal registry mcp fork NAMESPACE/SLUG --name my-mcp --output json
observal registry skill fork NAMESPACE/SLUG --version 1.2.0 --new-version 0.1.0 --output json
observal registry hook fork NAMESPACE/SLUG --team platform --visibility team --output json
observal registry prompt fork NAMESPACE/SLUG --name my-prompt --output json
observal registry sandbox fork NAMESPACE/SLUG --name my-sandbox --output json
```

All five commands return the new independent draft object with an `id`, `qualified_name`, `status`, and visibility-filtered `forked_from`. Never display or infer a source identity when `forked_from.available` is false. A private source must remain in its own private teamspace. A draft and a team-private fork do not increase public fork counts. After creation, edit using the new UUID (`observal registry TYPE edit FORK_UUID ... --output json`) and submit using the relevant type's draft submission command; verify the resulting review status. If a request's outcome is uncertain, inspect `registry TYPE my --output json` (or show by UUID where `my` is unavailable) before any retry.

## Edit

Draft, pending, and rejected items edit in place. Approved listings can enter a version flow.

```bash
observal registry mcp edit NAMESPACE/SLUG --from-file updates.json --output json
observal registry mcp edit NAMESPACE/SLUG --name new-name --description 'New description' --output json
observal registry skill edit NAMESPACE/SLUG --from-file updates.json --output json
observal registry hook edit NAMESPACE/SLUG --version 1.2.0 --event Stop --output json
observal registry prompt edit NAMESPACE/SLUG --template 'New template body' --output json
observal registry sandbox edit NAMESPACE/SLUG --image python:3.12-slim --output json
```

Verify the returned status and version. On an edit-lock conflict, do not overwrite blindly. Wait or ask the current editor to release it.

## Publish a version

Always supply an explicit semantic version in agent workflows so no prompt appears.

```bash
observal registry version publish mcp NAMESPACE/SLUG --version 1.2.0 --description 'What changed' --output json
observal registry version publish skill NAMESPACE/SLUG --version 0.3.0 --description 'New tasks' --output json
observal registry version publish hook NAMESPACE/SLUG --version 1.0.1 --description 'Bug fix' --output json
observal registry version publish prompt NAMESPACE/SLUG --version 2.0.0 --description 'Rewrite' --output json
observal registry version publish sandbox NAMESPACE/SLUG --version 1.1.0 --description 'New image' --extra '{"runtime_type":"docker","image":"python:3.12-slim"}' --output json
observal registry version list mcp NAMESPACE/SLUG --output json
```

Report review status separately from version creation.

## Archive and restore

```bash
observal registry mcp archive NAMESPACE/SLUG --yes --output json
observal registry skill archive NAMESPACE/SLUG --yes --output json
observal registry hook archive NAMESPACE/SLUG --yes --output json
observal registry prompt archive NAMESPACE/SLUG --yes --output json
observal registry sandbox archive NAMESPACE/SLUG --yes --output json
observal registry mcp unarchive NAMESPACE/SLUG --yes --output json
observal registry skill unarchive NAMESPACE/SLUG --yes --output json
```

Verify archived or restored state with the corresponding `show` command.

## Transfer ownership

```bash
observal registry mcp transfer-owner NAMESPACE/SLUG @username --yes --output json
observal registry skill transfer-owner NAMESPACE/SLUG @username --yes --output json
```

Ownership transfer changes who controls future edits and versions. Verify owner in the returned item.

## Co-authors

Co-authors can edit and publish. Add by email or username, remove by user UUID returned from list.

```bash
observal registry mcp co-authors list NAMESPACE/SLUG --output json
observal registry skill co-authors add NAMESPACE/SLUG @username --output json
observal registry hook co-authors remove NAMESPACE/SLUG USER_UUID --output json
```

## Error decisions

- Ambiguous name: use returned `qualified_name` or UUID.
- Edit lock: wait or coordinate, never force an overwrite.
- Conflict on approved item: inspect whether the server expects an edit or version command.
- Validation: correct only the named payload field and retry.
- Permission: report ownership or co-author requirement without escalating.
