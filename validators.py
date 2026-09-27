"""
validators.py — Post-LLM output validation and correction.

Checks composed messages for:
  - URLs (hard penalty from Meta/judge)
  - Voice taboos
  - CTA shape
  - Empty body
  - Repetition (caller's responsibility to pass last_body)
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"(https?://|www\.|magicpin\.|swiggy\.|zomato\.|instagram\.|facebook\.|wa\.me)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Known taboos per category (subset — full list in prompts.py)
# ---------------------------------------------------------------------------

_TABOOS: dict[str, list[str]] = {
    "dentists":    ["guaranteed", "100% safe", "completely cure", "miracle"],
    "salons":      ["guaranteed glow", "permanent results", "instant transformation", "miracle"],
    "restaurants": ["guaranteed packed house", "miracle marketing", "viral guarantee"],
    "gyms":        ["guaranteed weight loss", "shred in 7 days", "miracle transformation"],
    "pharmacies":  ["miracle cure", "guaranteed result", "100% safe"],
}

# ---------------------------------------------------------------------------
# Valid CTA values
# ---------------------------------------------------------------------------

VALID_CTAS = {
    "open_ended",
    "binary_yes_no",
    "binary_confirm_cancel",
    "multi_choice_slot",
    "none",
}

# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_and_fix(
    composed: dict,
    category_slug: str = "",
    last_body: Optional[str] = None,
    is_customer_facing: bool = False,
) -> Tuple[dict, list[str]]:
    """
    Validate and attempt to auto-fix a composed message dict.

    Returns:
        (fixed_composed, list_of_issues)
    Issues are warning strings. If body is empty after fix, caller should re-prompt.
    """
    issues: list[str] = []
    body: str = composed.get("body", "") or ""
    cta: str = composed.get("cta", "open_ended")
    rationale: str = composed.get("rationale", "")

    # 1. Empty body
    if not body.strip():
        issues.append("EMPTY_BODY: body is empty")
        return composed, issues

    # 2. URL check (-3 penalty each)
    if _URL_RE.search(body):
        body = _URL_RE.sub("", body).strip()
        issues.append("URL_REMOVED: URLs stripped from body (Meta policy)")

    # 3. Taboo check
    for taboo in _TABOOS.get(category_slug, []):
        if re.search(re.escape(taboo), body, re.IGNORECASE):
            issues.append(f"TABOO_WORD: '{taboo}' found in body for category {category_slug}")

    # 4. CTA normalization
    if cta not in VALID_CTAS:
        old_cta = cta
        cta = _infer_cta(body)
        issues.append(f"CTA_FIXED: '{old_cta}' → '{cta}'")

    # 5. Multiple CTA check (simple heuristic: multiple question marks + action words)
    cta_indicators = len(re.findall(r"\b(reply|click|call|say|text|press|WhatsApp)\b", body, re.IGNORECASE))
    if cta_indicators > 3:
        issues.append("MULTIPLE_CTA_RISK: Many CTA indicators — consider simplifying")

    # 6. Repetition guard
    if last_body and last_body.strip() == body.strip():
        issues.append("REPETITION: Body is identical to last message in this conversation")

    # 7. Long preamble check
    if re.match(r"^(i hope|hope you|i am reaching|greetings|dear|good (morning|afternoon|evening))", body, re.IGNORECASE):
        issues.append("PREAMBLE: Message starts with a greeting preamble — remove it")

    # 8. Re-introduction check (for follow-up messages)
    if re.search(r"\bi'?m vera\b|\bi am vera\b|\bthis is vera\b", body, re.IGNORECASE):
        issues.append("RE_INTRODUCTION: Bot re-introducing itself — remove in follow-up messages")

    # 9. Ensure rationale exists
    if not rationale.strip():
        rationale = f"Composed for trigger kind; anchored on available merchant/category data."
        issues.append("RATIONALE_ADDED: Auto-generated rationale")

    composed["body"] = body
    composed["cta"] = cta
    composed["rationale"] = rationale
    return composed, issues


def _infer_cta(body: str) -> str:
    """Infer a valid CTA type from message content."""
    b = body.lower()
    if any(w in b for w in ["reply yes", "reply no", "yes/no", "yes or no", "haan ya na"]):
        return "binary_yes_no"
    if any(w in b for w in ["reply confirm", "reply 1", "reply 2", "slot 1", "slot 2", "option 1"]):
        return "multi_choice_slot"
    if any(w in b for w in ["confirm to", "reply confirm", "type confirm"]):
        return "binary_confirm_cancel"
    return "open_ended"


def is_valid_response(composed: dict) -> bool:
    """Quick check: does the response have the minimum required fields?"""
    return bool(
        composed.get("body", "").strip()
        and composed.get("cta") in VALID_CTAS
    )
