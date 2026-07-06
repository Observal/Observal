# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Ownership transfer helpers."""

from __future__ import annotations


def transfer_entity_owner(entity, entity_type: str, current_user, target_user):
    previous_owner = entity.owner
    previous_owner_id = entity.created_by if entity_type == "agents" else entity.submitted_by
    new_owner = target_user.username or target_user.email

    entity.owner = new_owner
    entity.owner_org_id = target_user.org_id
    if entity_type == "agents":
        entity.created_by = target_user.id
    else:
        entity.submitted_by = target_user.id

    blocked_ids = {str(current_user.id), str(target_user.id)}
    entity.co_authors = [str(uid) for uid in (entity.co_authors or []) if str(uid) not in blocked_ids]
    return previous_owner, previous_owner_id
