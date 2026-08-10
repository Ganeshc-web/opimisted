"""Randomized narrative copy for goal / section DOCX pages."""

from __future__ import annotations

import random
import re

# Placeholder stem → three description options (paste {{stem_description}} in DOCX).
GOAL_DESCRIPTION_OPTIONS: dict[str, list[str]] = {
    "house_purchase": [
        "Based on the timeline and projected cost of this goal, we suggest prioritising disciplined investments to ensure your home purchase remains a planned milestone rather than a financial burden.",
        "Owning a home often involves one of life's largest commitments. Starting early can provide greater flexibility and reduce pressure as the goal approaches.",
        "A structured approach towards this goal can help you achieve the home you envision without compromising your other financial priorities.",
    ],
    "car_purchase": [
        "Since this goal directly impacts your lifestyle and convenience, a dedicated investment plan can help you make this purchase comfortably when required.",
        "Planning in advance for this purchase may help you avoid dipping into emergency reserves or disrupting long-term wealth creation.",
        "We suggest treating this goal as a planned expense so that future decisions can be made based on preference rather than financial constraints.",
    ],
    "home_renovation": [
        "Home improvement expenses often arise when least expected. Preparing for them in advance can help preserve both comfort and financial stability.",
        "Setting aside dedicated resources for this goal can allow you to enhance your living space without affecting other important commitments.",
        "A planned approach to renovation ensures that lifestyle upgrades happen on your terms and timeline.",
    ],
    "foreign_tour": [
        "Experiences and travel aspirations deserve the same financial attention as other life goals. Planning ahead can make them more enjoyable and stress-free.",
        "By allocating resources towards this goal today, you can look forward to future travel without compromising ongoing financial objectives.",
        "We suggest building this goal systematically so that memorable experiences do not become unexpected financial obligations.",
    ],
    "holiday_home": [
        "A holiday home is a meaningful lifestyle aspiration, and achieving it becomes more practical through disciplined preparation.",
        "Since this goal requires significant capital, early planning can provide greater flexibility and choice in the future.",
        "A dedicated investment strategy can help balance this aspiration alongside your essential financial goals.",
    ],
    "family_gifting": [
        "Celebrating important relationships often involves meaningful gestures, and planned giving helps preserve the joy behind them.",
        "We suggest budgeting for these milestones in advance so that generosity never comes at the cost of financial comfort.",
        "Thoughtful preparation can ensure that important occasions remain memorable without creating financial strain.",
    ],
    "charity": [
        "If giving back is important to you, incorporating it into your financial plan can help make your contributions both meaningful and sustainable.",
        "Planning for charitable goals ensures that your values are reflected in your financial decisions over time.",
        "A structured approach towards philanthropy allows you to create an impact while maintaining overall financial balance.",
    ],
    "child_birth": [
        "This phase often brings multiple planned and unplanned expenses, making early preparation especially valuable.",
        "Building a dedicated corpus for this goal can allow you to focus on the transition ahead with greater confidence.",
        "We suggest planning for these expenses in advance to minimize financial stress during an important life event.",
    ],
    "big_purchases": [
        "Major purchases can significantly influence cash flows, making advance planning an important part of financial well-being.",
        "We suggest preparing for large expenses systematically to avoid disrupting long-term investment goals.",
        "A dedicated strategy for significant purchases can help maintain financial discipline while meeting evolving needs.",
    ],
    "estate_for_children": [
        "Creating an estate is not only about transferring wealth but also about building a lasting financial legacy.",
        "We suggest approaching this goal with a long-term perspective to ensure future generations benefit from today's planning.",
        "Thoughtful preparation today can help provide security, opportunities, and continuity for those you care about.",
    ],
    "retirement": [
        "Retirement planning is ultimately about preserving independence and maintaining your desired lifestyle in the future.",
        "The earlier this goal is prioritized, the greater the opportunity to benefit from consistency and compounding.",
        "We suggest reviewing this goal periodically to ensure your retirement aspirations remain on track.",
    ],
    "child_graduation": [
        "Educational expenses continue to evolve, making early preparation essential for maintaining flexibility and choice.",
        "We suggest building this corpus steadily so that future academic opportunities can be pursued with confidence.",
        "Planning ahead can help ensure that financial considerations do not limit educational aspirations.",
    ],
    "child_post_graduation": [
        "Higher education often requires substantial resources, and a dedicated plan can make these aspirations more achievable.",
        "We suggest beginning preparations early to provide greater flexibility when important decisions arise.",
        "A disciplined approach towards this goal can help support future educational ambitions without compromising other priorities.",
    ],
    "child_marriage": [
        "Significant family celebrations deserve thoughtful planning to preserve both their meaning and financial balance.",
        "We suggest preparing for this milestone gradually so that the occasion can be celebrated with confidence and peace of mind.",
        "Early planning can help manage future expenses without affecting long-term financial security.",
    ],
    "child_other": [
        "Every aspiration is unique, and a flexible financial plan can help accommodate evolving priorities over time.",
        "We suggest revisiting this goal periodically to ensure that changing needs continue to be adequately supported.",
        "Preparing for future possibilities today can provide the confidence to pursue opportunities as they emerge.",
    ],
}

# Assessment goal_type → description stem (Lifestyle "Other" has no dedicated bank).
GOAL_TYPE_TO_DESCRIPTION_STEM: dict[str, str] = {
    "Home Purchase": "house_purchase",
    "Car Purchase": "car_purchase",
    "Home Renovation": "home_renovation",
    "Foreign Tour": "foreign_tour",
    "Holiday Home": "holiday_home",
    "Family Gifting": "family_gifting",
    "Charity": "charity",
    "Child Birth Expenses": "child_birth",
    "Big Purchases": "big_purchases",
    "Estate For Children": "estate_for_children",
    "Graduation": "child_graduation",
    "Post Graduation": "child_post_graduation",
    "Marriage": "child_marriage",
    "Other": "child_other",  # child Other templates; lifestyle Other shares this bank
}

DESCRIPTION_PLACEHOLDER_KEYS: tuple[str, ...] = tuple(
    f"{stem}_description" for stem in GOAL_DESCRIPTION_OPTIONS
)


def normalize_description(text: str) -> str:
    """Strip list numbering and collapse trailing double periods."""
    cleaned = re.sub(r"^\s*\d+\.\s*", "", (text or "").strip())
    cleaned = re.sub(r"\.\.+$", ".", cleaned)
    return cleaned


def description_stem_for_goal_type(goal_type: str | None) -> str | None:
    if not goal_type:
        return None
    return GOAL_TYPE_TO_DESCRIPTION_STEM.get(goal_type)


def pick_goal_descriptions(seed: str | None = None) -> dict[str, str]:
    """
    Pick one description per section.

    Same seed → same picks (stable per assessment). No seed → fresh random each call.
    Returns keys like house_purchase_description suitable for DOCX replace_placeholders.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    picks: dict[str, str] = {}
    for stem, options in GOAL_DESCRIPTION_OPTIONS.items():
        normalized = [normalize_description(opt) for opt in options if opt]
        if not normalized:
            picks[f"{stem}_description"] = ""
            continue
        picks[f"{stem}_description"] = rng.choice(normalized)
    return picks


def goal_description_from_picks(
    goal_type: str | None,
    picks: dict[str, str] | None,
) -> str:
    """Resolve {{goal_description}} for a goal page from typed picks."""
    stem = description_stem_for_goal_type(goal_type)
    if not stem or not picks:
        return ""
    return picks.get(f"{stem}_description", "") or ""
