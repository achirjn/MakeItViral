"""
Module 2 — Two-Phase Adaptive Activation Planner
-------------------------------------------------
Determines which extractors to run based on projection demand.

Phase A (baseline): extractors needed for REQUIRED_PROJECTION_FEATURES
                    plus infrastructure features (audio).
Phase B (adaptive): heavy extractors activated by heuristic signals
                    after baseline execution.

Planner is deterministic and side-effect free.
"""

from __future__ import annotations

from collections import deque
from typing import Sequence

from module2.logging_config import get_logger
from module2.projections.engine import REQUIRED_PROJECTION_FEATURES


logger = get_logger("planner")

# Infrastructure features that must always be in baseline even if
# not directly consumed by projections (needed by adaptive phase).
_BASELINE_EXTRAS: set[str] = {"embedding", "clip_embedding", "inference"}


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------


def topo_sort_extractors(extractors: Sequence) -> list:
    """
    Topologically sort extractors by their DAG `dependencies` property.
    Preserves insertion order for ties.
    """
    name_map = {e.name: e for e in extractors}
    in_degree: dict[str, int] = {e.name: 0 for e in extractors}
    adj: dict[str, list[str]] = {e.name: [] for e in extractors}

    active_names = set(name_map.keys())

    for e in extractors:
        for dep in e.dependencies:
            if dep in active_names:
                adj[dep].append(e.name)
                in_degree[e.name] += 1

    queue: deque[str] = deque(n for n in in_degree if in_degree[n] == 0)
    ordered: list = []

    while queue:
        name = queue.popleft()
        ordered.append(name_map[name])
        for child in adj.get(name, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return ordered


# ---------------------------------------------------------------------------
# Dependency closure (Fix 5)
# ---------------------------------------------------------------------------


def _compute_dependency_closure(
    demand: set[str],
    extractors: Sequence,
) -> set[str]:
    """
    Expand demand to full closure:
    - Add hard requires of any extractor whose produces overlap demand.
    - Add optional_requires ONLY if they are already in demand.
    Iterates until stable.
    """
    changed = True
    while changed:
        changed = False
        for e in extractors:
            if e.produces & demand:
                # Hard requirements — always pull in
                for dep in e.requires:
                    if dep not in demand:
                        demand.add(dep)
                        changed = True
                # Optional — only if already demanded (Fix 2)
                for dep in e.optional_requires:
                    if dep in demand and dep not in demand:
                        demand.add(dep)
                        changed = True
    return demand


# ---------------------------------------------------------------------------
# Backward demand propagation
# ---------------------------------------------------------------------------


def _resolve_demand(
    demand: set[str],
    extractors: Sequence,
) -> list:
    """
    Given a set of demanded logical features, backward-propagate
    through the extractor graph and return all extractors needed
    to produce those features (including transitive dependencies).
    """
    # Full closure first (Fix 5)
    demand = _compute_dependency_closure(set(demand), extractors)

    logger.debug(
        "resolve_demand_closure features=%s",
        sorted(demand),
    )

    # Build produces → extractor lookup
    producer_map: dict[str, object] = {}
    for e in extractors:
        for feat in e.produces:
            producer_map[feat] = e

    activated: set[str] = set()  # extractor names
    work: deque[str] = deque(demand)

    while work:
        feat = work.popleft()
        producer = producer_map.get(feat)
        if producer is None or producer.name in activated:
            continue

        activated.add(producer.name)
        # Hard requirements only (Fix 2: optional_requires do NOT create edges)
        for req_feat in producer.requires:
            if req_feat not in demand:
                demand.add(req_feat)
                work.append(req_feat)

    return [e for e in extractors if e.name in activated]


# ---------------------------------------------------------------------------
# Phase A — baseline extractors
# ---------------------------------------------------------------------------


def plan_baseline_extractors(extractors: Sequence) -> list:
    """
    Return the minimal extractor subset needed to compute
    REQUIRED_PROJECTION_FEATURES plus infrastructure features,
    topologically sorted.
    """
    # Fix 1: include audio in baseline for transcript gating
    baseline_demand = set(REQUIRED_PROJECTION_FEATURES) | _BASELINE_EXTRAS

    logger.debug(
        "activation_plan_demand phase=baseline features=%s",
        sorted(baseline_demand),
    )

    active = _resolve_demand(baseline_demand, extractors)

    logger.info(
        "activation_plan phase=baseline extractors=%s",
        [e.name for e in active],
    )

    return topo_sort_extractors(active)


# ---------------------------------------------------------------------------
# Phase B — adaptive extractors
# ---------------------------------------------------------------------------


def plan_adaptive_extractors(
    extractors: Sequence,
    context,
) -> list:
    """
    After baseline execution, decide which heavy extractors to activate
    based on heuristic signals available in context.

    Returns topologically sorted extractors that are NOT in baseline.
    """
    baseline_names = {e.name for e in plan_baseline_extractors(extractors)}
    demand: set[str] = set()

    # --- Read heuristic signals from intermediate outputs ---
    hook_entry = context.intermediate_outputs.get("hook") or {}
    hook_feats = (
        (hook_entry.get("features") or {}) if isinstance(hook_entry, dict) else {}
    )
    hook_score = hook_feats.get("hook_motion_score")
    scene_rate = hook_feats.get("hook_scene_change_rate")

    motion_entry = context.intermediate_outputs.get("motion") or {}
    motion_feats = (
        (motion_entry.get("features") or {}) if isinstance(motion_entry, dict) else {}
    )
    motion_score = motion_feats.get("motion_score")

    metadata = context.metadata or {}

    # --- Heuristic 1: gray-zone hook → LLM hook ---
    if isinstance(hook_score, (int, float)) and 0.25 <= hook_score <= 0.75:
        demand.update({"llm_hook_score", "llm_hook_confidence"})

    if not demand:
        logger.debug(
            "activation_plan phase=adaptive result=no_demand",
            extra={"reel_id": context.reel_id},
        )
        return []

    logger.debug(
        "activation_plan_demand phase=adaptive features=%s",
        sorted(demand),
        extra={"reel_id": context.reel_id},
    )

    # Resolve all extractors needed
    all_active = _resolve_demand(demand, extractors)

    # Exclude extractors already in baseline (Fix 6: name-based dedup)
    adaptive_only = [e for e in all_active if e.name not in baseline_names]

    if adaptive_only:
        logger.info(
            "activation_plan phase=adaptive extractors=%s",
            [e.name for e in adaptive_only],
            extra={"reel_id": context.reel_id},
        )

    return topo_sort_extractors(adaptive_only)
