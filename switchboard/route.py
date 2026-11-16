"""Score profiled skills against Claude's structured description of a task.

Past choices only break ties between equal scores; they never lift a weaker fit above a better one.
"""
from __future__ import annotations

from collections import Counter

ROLES = ("performs", "assists", "meta")  # kept equal to profiles.ROLES (tests/test_route checks it)

W_TARGET, W_FOCUS, W_STACK, W_DEPTH, W_COST = 3, 2, 1, 1, 1
LIMIT = 10  # a coarse shortlist: Claude picks the 2–3 to offer by best_for / not_for
FULL_TAGS = 3  # a field with more tags than this is discounted
COST_RANK = {"single-pass": 0, "multi-agent": 1, "workflow": 2}  # tie-break: the lighter skill first
NEXT = ("Pick the 2–3 candidates whose best_for/not_for fit this task best and ask the user with AskUserQuestion "
        "(one option per skill, reason in its description, a past choice as a label), then call record_choice. "
        "If only one fits clearly, call record_choice with it and say which.")


def _list(v):
    return v if isinstance(v, list) else [v] if isinstance(v, str) else []


def _fit(task_vals, prof_vals) -> float:
    """Share of the task's tags the profile covers, so a skill that matches only part of the task
    ranks below one that matches all of it; a field listing more than FULL_TAGS tags is scaled by
    FULL_TAGS/len, so a tag-stuffed profile cannot buy a top rank."""
    task, prof = set(_list(task_vals)), set(prof_vals or [])
    if not task or not prof:
        return 0.0
    return len(task & prof) / len(task) * min(1.0, FULL_TAGS / len(prof))


def _precision(task: dict, p: dict) -> float:
    """Tie-break only: matched share of the profile's own target and focus tags (the more focused skill first)."""
    return sum(len(set(_list(task.get(k))) & set(p.get(k) or [])) / len(p.get(k)) for k in ("targets", "focus") if p.get(k))


def score(task: dict, p: dict) -> float:
    s = W_TARGET * _fit(task.get("targets"), p.get("targets"))
    s += W_FOCUS * _fit(task.get("focus"), p.get("focus"))
    stack = set(_list(task.get("stack")))
    if stack and ("any" in (p.get("stack") or []) or stack & set(p.get("stack") or [])):
        s += W_STACK
    if task.get("depth") and task.get("depth") == p.get("depth"):
        s += W_DEPTH
    if task.get("cost") and task.get("cost") == p.get("cost"):
        s += W_COST
    return round(s, 2)


def route(task: dict, profiles: dict, inventory: dict, past: list[dict]) -> dict:
    """`profiles` {id: profile}; `inventory` the current skills mapping {id: record}."""
    cat = task.get("category") if isinstance(task, dict) else None
    if not isinstance(cat, str) or not cat:
        raise ValueError("task.category is required")
    want = task.get("role") if task.get("role") in ROLES else "performs"
    stack = set(_list(task.get("stack")))
    # a skill tied to other languages (no "any", no overlap with the task's stack) sorts below its role group
    off_stack = lambda p: bool(p.get("stack")) and "any" not in p["stack"] and not stack & set(p["stack"])
    # matching role first, then profiles not yet given a role, then the rest; score orders within each group
    group = lambda p: (0 if p.get("role") == want else 1 if "role" not in p else 2) * 2 + off_stack(p)
    picked = Counter(r.get("chosen") for r in past)
    scored = [(group(p), score(task, p), COST_RANK.get(p.get("cost"), 1), _precision(task, p), picked[sid], sid)
              for sid, p in profiles.items() if sid in inventory and cat in (p.get("categories") or [])]
    # past picks right after score: precision is a continuous float, so behind it they would almost never act
    scored.sort(key=lambda x: (x[0], -x[1], -x[4], x[2], -x[3], x[5]))
    cands = []
    for _, s, *_, sid in scored[:LIMIT]:
        p = profiles[sid]
        cands.append({"id": sid, "score": s, "stale": p.get("content_hash") != inventory[sid].get("content_hash"),
                      "profile": p,
                      "past_choices": [r.get("date") for r in past if r.get("chosen") == sid]})
    overlap = len(cands) >= 2
    return {"candidates": cands, "overlap": overlap, **({"next": NEXT} if overlap else {})}


def overlap_categories(profiles: dict, inventory: dict) -> list[str]:
    n = Counter(c for sid, p in profiles.items() if sid in inventory for c in set(p.get("categories") or []))
    return sorted(c for c, k in n.items() if k >= 2)
