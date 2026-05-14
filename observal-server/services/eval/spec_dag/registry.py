# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Spec DAG registry — Postgres CRUD + schema_version gating.

The Pydantic ``SpecDAG`` is dumped to JSON and stored in
``eval_spec_dags.dag_json``. Reads route through ``load_spec_dag`` which
refuses any row whose ``schema_version`` is missing or < 2 — those are
v1 path-oriented specs and must be migrated explicitly via the
``observal admin eval spec-dag migrate`` CLI command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from models.eval_spec_dag import EvalSpecDAG
from services.eval.spec_dag.models import SpecDAG

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

CURRENT_SCHEMA_VERSION = 2


def load_spec_dag(dag_json: dict[str, Any]) -> SpecDAG:
    """Parse a ``dag_json`` blob into a SpecDAG. Refuse v1.

    Detection: a v2 spec carries ``schema_version >= 2``. v1 (path-oriented)
    blobs have either no ``schema_version`` field or have v1-shape keys
    (``nodes``/``edges`` at top level instead of ``outcome_assertions``).
    """
    schema_version = dag_json.get("schema_version", 1)
    is_v1_shape = "nodes" in dag_json or "edges" in dag_json
    if schema_version < CURRENT_SCHEMA_VERSION or is_v1_shape:
        task_type = dag_json.get("task_type", "?")
        raise ValueError(
            f"SpecDAG schema version {schema_version} is path-oriented (legacy). "
            f"Migrate to outcome-oriented (schema_version={CURRENT_SCHEMA_VERSION}) "
            f"before using. Run: observal admin eval spec-dag migrate {task_type}"
        )
    return SpecDAG.from_json(dag_json)


async def register(
    db: AsyncSession,
    dag: SpecDAG,
    *,
    created_by: str | None = None,
) -> uuid.UUID:
    """Insert a new spec DAG row. Caller is responsible for unique (task_type, version)."""
    row = EvalSpecDAG(
        task_type=dag.task_type,
        version=dag.version,
        dag_json=dag.to_json(),
        source=dag.source.value,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row.id


async def list_by_task_type(db: AsyncSession, task_type: str) -> list[EvalSpecDAG]:
    stmt = select(EvalSpecDAG).where(EvalSpecDAG.task_type == task_type).order_by(EvalSpecDAG.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars())


async def get(db: AsyncSession, dag_id: uuid.UUID) -> SpecDAG | None:
    row = await db.get(EvalSpecDAG, dag_id)
    if row is None:
        return None
    return load_spec_dag(row.dag_json)


async def get_latest(db: AsyncSession, task_type: str) -> SpecDAG | None:
    stmt = (
        select(EvalSpecDAG).where(EvalSpecDAG.task_type == task_type).order_by(EvalSpecDAG.created_at.desc()).limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return load_spec_dag(row.dag_json)


# ── v1 → v2 migration ──


def migrate_v1_to_v2(v1_json: dict[str, Any]) -> SpecDAG:
    """Convert a v1 path-oriented dag_json blob into a v2 SpecDAG.

    Mapping rules per the unified prompt's Step 7:
    - Each old ``SpecNode`` with a ``match_predicate`` → ``TOOL_WAS_CALLED``
      OutcomeAssertion. Param constraints are *narrowed* to look-like-id
      keys only (``id``, ``_id`` suffix, things that aren't free-text content).
    - Each old ``SpecEdge`` → ``StepConstraint`` with severity="soft".
    - Old ``forbidden_actions`` → ``DomainInvariant`` with TOOL_WAS_CALLED check
      (semantics: invariant is violated when the tool *is* called).
    - Old ``permitted_extras`` → dropped.
    """
    from services.eval.spec_dag.models import (
        DomainInvariant,
        OutcomeAssertion,
        OutcomeCheck,
        OutcomeCheckType,
        SpecSource,
        StepConstraint,
    )

    task_type = v1_json.get("task_type", "")
    old_version = str(v1_json.get("version", "1"))
    nodes = v1_json.get("nodes") or []
    edges = v1_json.get("edges") or []
    forbidden = v1_json.get("forbidden_actions") or []

    assertions: list[OutcomeAssertion] = []
    for n in nodes:
        node_id = n.get("id") or "node"
        pred = n.get("match_predicate") or {}
        tool_name = pred.get("tool_name") or ""
        if not tool_name:
            continue
        params: dict[str, Any] = {"tool_name": tool_name, "min_count": 1}
        old_pc = pred.get("param_constraints") or {}
        narrowed = {k: v for k, v in old_pc.items() if _looks_like_identifier_key(k, v)}
        if narrowed:
            params["param_constraints"] = narrowed
        assertions.append(
            OutcomeAssertion(
                assertion_id=node_id,
                description=n.get("description") or f"migrated from v1 node {node_id}",
                check=OutcomeCheck(check_type=OutcomeCheckType.TOOL_WAS_CALLED, params=params),
                weight=float(n.get("weight", 1.0)),
                required=True,
            )
        )

    constraints: list[StepConstraint] = []
    for e in edges:
        src = e.get("src")
        dst = e.get("dst")
        if not src or not dst:
            continue
        # map node_id → tool_name via `nodes`
        src_tool = next((nn.get("match_predicate", {}).get("tool_name") for nn in nodes if nn.get("id") == src), None)
        dst_tool = next((nn.get("match_predicate", {}).get("tool_name") for nn in nodes if nn.get("id") == dst), None)
        if not src_tool or not dst_tool:
            continue
        constraints.append(
            StepConstraint(
                constraint_id=f"{src}_before_{dst}",
                description=f"migrated from v1 edge {src} → {dst}",
                before_tool=src_tool,
                after_tool=dst_tool,
                weight=1.0,
                severity="soft",
            )
        )

    invariants: list[DomainInvariant] = []
    for tool_name in forbidden:
        if not isinstance(tool_name, str) or not tool_name:
            continue
        invariants.append(
            DomainInvariant(
                invariant_id=f"forbidden_{tool_name}",
                description=f"migrated from v1 forbidden_actions: must not call {tool_name}",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.TOOL_WAS_CALLED,
                    params={"tool_name": tool_name, "min_count": 1},
                ),
                severity="major",
            )
        )

    return SpecDAG(
        schema_version=CURRENT_SCHEMA_VERSION,
        task_type=task_type,
        version=f"{old_version}+v2",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=assertions,
        step_constraints=constraints,
        domain_invariants=invariants,
    )


def _looks_like_identifier_key(key: str, value: Any) -> bool:
    if not isinstance(value, (str, int, bool)) and value is not None:
        return False
    k = key.lower()
    if k.endswith("_id") or k == "id":
        return True
    return k in {"name", "version", "status", "type"}


async def migrate_task_type(db: AsyncSession, task_type: str) -> list[uuid.UUID]:
    """Find every v1 row for `task_type`; insert a v2 successor for each.

    Idempotent: rows whose ``dag_json.schema_version`` is already >= 2 are skipped.
    """
    stmt = select(EvalSpecDAG).where(EvalSpecDAG.task_type == task_type)
    rows = list((await db.execute(stmt)).scalars())
    new_ids: list[uuid.UUID] = []
    for row in rows:
        blob = dict(row.dag_json or {})
        if blob.get("schema_version", 1) >= CURRENT_SCHEMA_VERSION and "nodes" not in blob:
            continue
        v2 = migrate_v1_to_v2(blob)
        new_ids.append(await register(db, v2, created_by=row.created_by))
    return new_ids


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "get",
    "get_latest",
    "list_by_task_type",
    "load_spec_dag",
    "migrate_task_type",
    "migrate_v1_to_v2",
    "register",
]
