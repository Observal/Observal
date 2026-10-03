<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Sync an MCP server from GitHub

An MCP server listed with a git repository can publish new versions on its own. Add a GitHub webhook to the repository, and Observal re-reads the repository and publishes a new version whenever you push or publish a release. You no longer have to run `observal registry mcp edit` after every change.

## What a sync does

1. GitHub sends a signed webhook to Observal.
2. Observal checks the signature and the repository. Then it queues the sync and replies right away.
3. A background worker fetches the repository, runs the same analysis as `observal registry mcp submit --git`, and publishes a new version.

Each sync creates a new version and leaves earlier versions alone. Agents pinned to an earlier version keep installing it, because agent lockfiles pin version content by digest.

The new version starts as a copy of the current version, then picks up these changes from the repository:

| Field | What changes |
| --- | --- |
| Tools | Replaced with the tools found in the repository |
| Environment variables | Newly found variables are added as optional. Variables you already listed keep your descriptions |
| Framework | Updated when one is detected |
| Command, args, Docker image, setup instructions | Filled in only when the listing has none, and only from an image the repository declares in a compose file or README. A guessed image name is never stored. Values you set by hand are kept |
| Description | Kept |
| Commit and ref | The synced commit sha and the branch or tag name are recorded on the version |
| Changelog | The head commit message for a push, or the release notes for a release |

Synced versions are approved and published right away, without review. Anyone who can push to the tracked branch, or publish a release, can change what the listing installs. Turn on sync only for repositories whose write access you trust.

## Triggers and version numbers

Choose either trigger, or both:

| Trigger | Fires on | Version |
| --- | --- | --- |
| Push | A push to the tracked branch. The default is the repository's default branch | The version in `pyproject.toml` or `package.json` when it is higher than every existing version. Otherwise the highest existing version with its patch number raised, so `1.2.3` becomes `1.2.4` |
| Release | A GitHub release being published. Drafts are ignored | The release tag, either `v1.2.3` or `1.2.3`. A tag that is not a semantic version is ignored |

If fetching the repository fails, the sync retries twice, 15 and then 30 seconds later, before it is marked failed. This covers network errors and a release whose tag GitHub has not finished publishing.

A push sync always fetches the branch tip when the job runs, not the commit named in the delivery. Several quick pushes therefore publish the newest code, and a commit that is already published is skipped. A release whose version already exists is skipped too. A release older than the current latest version is published but does not become the latest.

## Set it up

You must own the listing, or be a co-author or an admin. The listing must have a git repository URL, and a reviewer must have approved it at least once. Synced versions skip review, so the first version still goes through it.

### 1. Turn on sync

From the CLI:

```bash
observal registry mcp sync enable alice/weather-mcp                    # push only
observal registry mcp sync enable alice/weather-mcp --release          # push and release
observal registry mcp sync enable alice/weather-mcp --release --no-push --branch stable
```

Or open the MCP server in the web app and use the **Sync** tab.

Observal returns a webhook URL and a secret. The secret is shown only once. If you lose it, rotate it with `observal registry mcp sync rotate-secret`.

### 2. Add the webhook in GitHub

In the repository, open **Settings > Webhooks > Add webhook** and enter:

| Setting | Value |
| --- | --- |
| Payload URL | The webhook URL from step 1 |
| Content type | `application/json` |
| Secret | The secret from step 1 |
| Events | **Just the push event** for push sync. For release sync, choose **Let me select individual events** and tick **Releases**, plus **Pushes** if you use both |

GitHub sends a `ping` right away. Its delivery should show a `202` response.

GitHub must be able to reach your Observal server. Set `deployment.public_url` so the webhook URL uses your public address. If Observal runs on a private network, see [Private deployments](#private-deployments).

### 3. Check the result

```bash
observal registry mcp sync status alice/weather-mcp
observal registry mcp sync run alice/weather-mcp   # sync the tracked branch now
```

Deliveries that are ignored, such as a push to another branch, do not change the sync status. GitHub's **Recent Deliveries** page shows the reason in the response body.

## Private deployments

github.com delivers webhooks over the public internet, so an Observal install inside a private network needs one public path for them. Expose only the webhook receiver, `POST /api/v1/webhooks/github/*`, through a public load balancer or reverse proxy, ideally restricted to [GitHub's webhook IP ranges](https://api.github.com/meta) (the `hooks` list). Then set `WEBHOOK_PUBLIC_URL` on the API to that public address, for example `https://hooks.observal.example.com`. The **Sync** tab shows Payload URLs under it, while everything else keeps using the private address.

* **AWS Terraform:** set `enable_github_webhook_ingress = true`. See [GitHub webhooks on a private install](../self-hosting/aws-terraform.md#github-webhooks-on-a-private-install).
* **GitHub Enterprise Server** on the same network can reach Observal directly and needs none of this.

## Private repositories

Observal fetches the repository with the server's `GIT_CLONE_TOKEN`, the same token used to analyze git submissions. The token needs read access to the repository. Self-hosted GitHub Enterprise on a private network also needs `ALLOW_INTERNAL_GIT_URLS=true`.

## Security

- Each listing has its own secret, stored encrypted. Deliveries without a valid `X-Hub-Signature-256` signature are rejected with `401`.
- A delivery from a different repository than the listing's git URL is rejected with `422`.
- Synced versions are published as the user who last turned on or changed sync. If that user no longer owns the listing, syncs fail until an owner turns sync off and on again.
- The receiver allows 60 deliveries per minute per client address.

## Turn it off

```bash
observal registry mcp sync disable alice/weather-mcp
```

Published versions stay. Remove the webhook from the repository's settings as well.
