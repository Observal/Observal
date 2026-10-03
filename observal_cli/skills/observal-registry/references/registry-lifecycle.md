<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-FileCopyrightText: 2026 Kaushik <kaushikrjpm10@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Registry lifecycle

## Contents

- Read owned state
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

## Skill folder version management

Skills with extra files (scripts, templates, assets) use folder-based authoring.

### Save a folder draft

```bash
observal registry skill submit --from-dir ./my-skill --name my-skill --description 'My skill' --output json
```

The response contains `listing_id`, `version_id` and `revision`, not a reviewed or installable release. Hidden/excluded paths are reported; machine-readable submissions refuse omissions and likely-sensitive paths unless the human has inspected them and explicitly adds `--allow-excluded` and/or `--allow-sensitive`. Do not use the flag to bypass an uncertain directory. Resource-bearing review and delivery refuse while the rollout setting remains off. After review is separately enabled, submit that **exact** saved version:

```bash
observal registry skill submit --submit LISTING_ID --version-id VERSION_UUID --output json
```

### Replace all files in a version

```bash
observal registry skill replace-files NAMESPACE/SLUG --version-id UUID --from-dir ./my-skill --revision REVISION --output json
```

This replaces the **entire** draft tree. Inspect the local snapshot first: excluded paths require explicit `--allow-excluded` (they may be deleted remotely) and likely-sensitive files require `--allow-sensitive` in machine mode. No unacknowledged replacement request is sent.

### Withdraw a pending version

```bash
observal registry skill withdraw NAMESPACE/SLUG --version-id UUID --revision REVISION --output json
```

### Rebase a draft on current approved

```bash
observal registry skill rebase NAMESPACE/SLUG --version-id DRAFT_UUID --revision DRAFT_REV \
    --current-version-id APPROVED_UUID --current-revision APPROVED_REV --new-version 1.2.0 --output json
```

### Export a version to local directory

```bash
observal registry skill export NAMESPACE/SLUG ./local-dir --output json
observal registry skill export NAMESPACE/SLUG ./local-dir --version-id UUID --output json
```

Export requires a **new** destination directory, downloads and verifies every declared file before writing, and preserves binary attachments. Without `--version-id` it selects a cleared approved release, never an unreviewed draft.

Always use `--output json` for machine-readable responses. Verify revision fields match before mutations.

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
