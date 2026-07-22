<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Teamspaces

A teamspace is a shared namespace that a group of users publishes under. Each teamspace has a unique handle (for example `platform-tools`) that is reserved across the whole registry, so a user cannot take a username that collides with a team handle and vice versa.

## Roles

Every member of a teamspace has one of three roles:

| Role | Can |
| --- | --- |
| `owner` | Manage members, edit the teamspace, delete the teamspace |
| `reviewer` | (Reserved for team publishing approval, see below) |
| `member` | View the team roster |

Global admins can manage any teamspace regardless of membership. A teamspace always keeps at least one owner; the last owner cannot leave or be removed without first transferring ownership.

## Creating a teamspace

Any user with the `reviewer` role or above can create a teamspace from the web UI under **Registry, Teamspaces**. The creator becomes the first owner. The handle is derived from the name you choose but can be edited, and it must pass the namespace rules: 3 to 32 lowercase letters, digits, and hyphens, starting and ending with a letter or digit.

## Managing members

Team owners and global admins can add members by searching for a user by name, email, or username, and assigning a role. Members can leave a team on their own unless they are the last owner.

## What is not here yet

Team-scoped publishing (publishing an agent or component directly into a team namespace, and team-private visibility for components and agents) is a follow-up slice. Today teamspaces establish identity, membership, and handle reservation only.
