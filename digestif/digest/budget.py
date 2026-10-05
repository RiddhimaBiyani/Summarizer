"""Deterministic time-budget allocation for nightly digests."""

import math
from typing import Any

from digestif.observability import logger


def _num_or_default(value: Any, default: float) -> float:
    """Like `value or default`, but preserves a legitimate 0/0.0 instead of
    treating it as falsy and silently substituting the default."""
    return float(value) if value is not None else default


class BudgetItem:
    def __init__(self, item: dict[str, Any]):
        self.id = item["id"]
        self.title = item.get("title") or f"Item #{self.id}"
        self.priority = _num_or_default(item.get("priority"), 0.5)
        self.original_minutes = _num_or_default(item.get("original_minutes"), 2.0)
        self.word_count = int(_num_or_default(item.get("word_count"), 500))
        self.tier = "standard"  # "deep" | "standard" | "quick_hit" | "carryover"
        self.target_words = 0


def allocate_digest_budget(
    items: list[dict[str, Any]],
    budget_minutes: int = 20,
    wpm: int = 230,
) -> tuple[list[BudgetItem], dict[str, int]]:
    """Allocates words across candidate items matching Section 13.3 specifications."""
    if not items:
        return ([], {"total_target_words": 0, "budget_words": budget_minutes * wpm})

    total_budget_words = budget_minutes * wpm
    overview_reserve = int(0.10 * total_budget_words)
    quiz_reserve = int(0.05 * total_budget_words)
    w_remaining = total_budget_words - overview_reserve - quiz_reserve

    budget_items = [BudgetItem(it) for it in items]
    # Sort descending by priority
    budget_items.sort(key=lambda b: b.priority, reverse=True)

    # Assign initial tiers
    # Top 20% or priority >= 0.7 become 'deep', rest 'standard'
    deep_count = max(1, math.ceil(len(budget_items) * 0.20))
    for idx, b_item in enumerate(budget_items):
        if idx < deep_count or b_item.priority >= 0.7:
            b_item.tier = "deep"
        else:
            b_item.tier = "standard"

    # Iterative allocation & demotion loop
    max_demotions = len(budget_items)
    for _ in range(max_demotions):
        active_items = [b for b in budget_items if b.tier in ("deep", "standard")]
        quick_hits = [b for b in budget_items if b.tier == "quick_hit"]

        quick_hits_words = len(quick_hits) * 35
        available_for_active = max(0, w_remaining - quick_hits_words)

        if not active_items:
            break

        # Compute raw weights: share_i ∝ priority_i * (1 + ln(1 + original_minutes_i))
        weights = []
        for b in active_items:
            weight = b.priority * (1.0 + math.log(1.0 + max(0.1, b.original_minutes)))
            weights.append(weight)

        total_weight = sum(weights) or 1.0

        total_active_target = 0
        for b, weight in zip(active_items, weights):
            raw_share = (weight / total_weight) * available_for_active
            min_words = 350 if b.tier == "deep" else 160
            max_words = 1100

            clamped = max(min_words, min(int(raw_share), max_words))
            # Never exceed 50% of original word count (with 150 min floor)
            length_ceiling = max(150, int(0.5 * b.word_count))
            final_words = min(clamped, length_ceiling)
            b.target_words = final_words
            total_active_target += final_words

        if total_active_target + quick_hits_words <= w_remaining or len(active_items) <= 1:
            break

        # Overflow: demote lowest priority active item to quick_hit
        lowest_item = active_items[-1]
        lowest_item.tier = "quick_hit"
        lowest_item.target_words = 35
        logger.debug("Demoted item to quick_hit due to budget overflow", item_id=lowest_item.id)

    # Overflow beyond quick_hit capacity (max 12) -> carryover
    quick_count = 0
    for b in budget_items:
        if b.tier == "quick_hit":
            quick_count += 1
            if quick_count > 12:
                b.tier = "carryover"
                b.target_words = 0

    total_allocated = sum(b.target_words for b in budget_items if b.tier != "carryover")
    stats = {
        "budget_words": total_budget_words,
        "content_allocated_words": total_allocated,
        "overview_reserve": overview_reserve,
        "total_target_words": total_allocated + overview_reserve + quiz_reserve,
    }

    return (budget_items, stats)
