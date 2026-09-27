"""
composer.py — LLM-powered message composition engine.

Uses Google Gemini (gemini-2.0-flash) via the new google-genai SDK.
Temperature=0 for determinism. Dispatches different prompt framings per trigger.kind.
Validates output post-LLM.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from google import genai
from google.genai import types as genai_types

from prompts import build_system_prompt, build_user_prompt
from validators import validate_and_fix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

_CLIENT: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable not set. "
            "Copy .env.example to .env and add your key from aistudio.google.com/app/apikey"
        )
    _CLIENT = genai.Client(api_key=api_key)
    return _CLIENT


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

class Composer:
    """
    Composes WhatsApp messages for merchants and their customers.
    compose() returns dict with keys: body, cta, rationale
    """

    MODEL = "gemini-3.8-flash"
    MAX_RETRIES = 2

    def __init__(self):
        # Validate API key is set on startup
        _get_client()

    def compose(
        self,
        trigger: dict,
        merchant: dict,
        category: dict,
        customer: Optional[dict] = None,
        conversation_history: Optional[list] = None,
        mode: str = "compose",
        merchant_last_message: Optional[str] = None,
        last_bot_body: Optional[str] = None,
    ) -> dict:
        """
        Compose a message and validate it.
        Returns {body, cta, rationale} dict.
        """
        cat_slug = category.get("slug", "")
        is_customer_facing = customer is not None

        system_prompt = build_system_prompt(cat_slug, is_customer_facing)
        user_prompt = build_user_prompt(
            trigger=trigger,
            merchant=merchant,
            category=category,
            customer=customer,
            conversation_history=conversation_history,
            mode=mode,
            merchant_last_message=merchant_last_message,
        )

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

        composed = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                client = _get_client()
                response = client.models.generate_content(
                    model=self.MODEL,
                    contents=full_prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=600,
                        response_mime_type="application/json",
                    ),
                )
                raw = response.text
                composed = self._parse(raw)
                if composed:
                    break
            except Exception as e:
                logger.warning(f"Gemini attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(1.0)
                else:
                    logger.error("All Gemini attempts failed; using fallback")
                    return self._fallback(trigger, merchant, category, customer, merchant_last_message)

        if not composed:
            return self._fallback(trigger, merchant, category, customer, merchant_last_message)

        # Post-LLM validation
        composed, issues = validate_and_fix(
            composed,
            category_slug=cat_slug,
            last_body=last_bot_body,
            is_customer_facing=is_customer_facing,
        )
        if issues:
            logger.info(f"Validation issues for {trigger.get('kind')}: {issues}")

        if not composed.get("body", "").strip():
            return self._fallback(trigger, merchant, category, customer, merchant_last_message)

        return composed

    def _parse(self, raw: str) -> Optional[dict]:
        """Parse JSON from LLM response."""
        if not raw:
            return None
        # Direct JSON parse
        try:
            data = json.loads(raw)
            if "body" in data:
                return data
        except json.JSONDecodeError:
            pass
        # Fallback: extract JSON block with body key
        match = re.search(r'\{[\s\S]*?"body"[\s\S]*?\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _fallback(
        self,
        trigger: dict,
        merchant: dict,
        category: dict,
        customer: Optional[dict] = None,
        merchant_last_message: Optional[str] = None,
    ) -> dict:
        """Deterministic fallback when LLM fails — uses context data."""
        identity = merchant.get("identity", {})
        name = identity.get("owner_first_name") or identity.get("name", "there")
        cat_slug = category.get("slug", "unknown")
        kind = trigger.get("kind", "update")
        perf = merchant.get("performance", {})
        peer = category.get("peer_stats", {})

        if merchant_last_message and any(w in merchant_last_message.lower() for w in ["yes", "ok", "go ahead", "do it"]):
            return {
                "body": f"Done! I've prepared the draft for your {cat_slug} campaign. Please confirm to proceed.",
                "cta": "binary_confirm_cancel",
                "rationale": "Fallback for intent commitment.",
            }

        if customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            body = (
                f"Hi {cust_name}! {identity.get('name', 'We')} here — "
                f"just checking in. Would you like to book your next appointment? "
                f"Reply YES and we'll sort it out 🙂"
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "rationale": f"Fallback customer-facing message for {kind} trigger.",
            }

        ctr = perf.get("ctr", 0) or 0
        peer_ctr = peer.get("avg_ctr", 0) or 0
        views = perf.get("views", 0)

        if ctr and peer_ctr and ctr < peer_ctr:
            body = (
                f"Hi {name}! Quick check — your profile CTR is {ctr:.1%} "
                f"vs category avg {peer_ctr:.1%}. "
                f"Want me to suggest 2-3 quick fixes? Roughly 5 minutes."
            )
            cta = "binary_yes_no"
        else:
            body = (
                f"Hi {name}! Your {cat_slug} profile had {views:,} views this month. "
                f"Want me to review what's working and suggest the next step?"
            )
            cta = "open_ended"

        return {
            "body": body,
            "cta": cta,
            "rationale": f"Deterministic fallback for {kind} trigger. LLM unavailable.",
        }
