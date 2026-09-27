"""
bot.py — Vera: magicpin Merchant AI Assistant
=============================================

FastAPI server implementing all 6 judge endpoints:
  GET  /v1/healthz
  GET  /v1/metadata
  POST /v1/context
  POST /v1/tick
  POST /v1/reply
  POST /v1/teardown

Usage:
  1. Set GEMINI_API_KEY in environment (or .env file)
  2. pip install -r requirements.txt
  3. uvicorn bot:app --host 0.0.0.0 --port 8080

For local testing:
  export BOT_URL=http://localhost:8080
  python judge_simulator.py
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

from composer import Composer
from context_store import ContextStore
from conversation_manager import ConversationManager

# ---------------------------------------------------------------------------
# App + globals
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vera")

app = FastAPI(title="Vera — magicpin Merchant AI", version="1.0.0")
START_TIME = time.time()

store = ContextStore()
conv_mgr = ConversationManager()
composer = Composer()

# Track suppressed suppression_keys to prevent duplicate sends
_sent_suppressions: set[str] = set()

# Track conversation_ids we've already started (tick can only start NEW ones)
_active_conv_ids: set[str] = set()


# ---------------------------------------------------------------------------
# Health & Metadata
# ---------------------------------------------------------------------------

@app.get("/v1/healthz")
async def healthz():
    counts = store.counts()
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts,
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": os.getenv("TEAM_NAME", "Vera Bot"),
        "team_members": [os.getenv("TEAM_MEMBER", "Tanishka Singh")],
        "model": "gemini-2.0-flash",
        "approach": (
            "LLM-powered composition (Gemini 2.0 Flash, temp=0) with per-trigger-kind prompt dispatch, "
            "category voice injection (5 categories), post-LLM validation (URL strip, taboo, CTA shape, "
            "repetition guard), and conversation state machine (auto-reply, intent, hostile handling)."
        ),
        "contact_email": os.getenv("CONTACT_EMAIL", "team@example.com"),
        "version": "1.0.0",
        "submitted_at": os.getenv("SUBMITTED_AT", datetime.now(timezone.utc).isoformat()),
    }


# ---------------------------------------------------------------------------
# Context push
# ---------------------------------------------------------------------------

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str = ""


@app.post("/v1/context")
async def push_context(body: CtxBody):
    if body.scope not in ContextStore.VALID_SCOPES:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"scope must be one of {list(ContextStore.VALID_SCOPES)}"},
        )

    accepted, current_version, ack_id = store.push(
        body.scope, body.context_id, body.version, body.payload
    )

    if not accepted:
        if ack_id == "stale_version":
            return JSONResponse(
                status_code=409,
                content={
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": current_version,
                },
            )
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": ack_id},
        )

    logger.info(f"Context accepted: scope={body.scope} id={body.context_id} v{body.version}")
    return {
        "accepted": True,
        "ack_id": ack_id,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Tick — proactive send
# ---------------------------------------------------------------------------

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    """
    Decide which triggers to act on and compose messages.
    Returns up to 20 actions per tick.
    """
    actions = []

    # Sort by urgency (highest first)
    trigger_items = []
    for trg_id in body.available_triggers:
        trg = store.get("trigger", trg_id)
        if trg:
            trigger_items.append((trg.get("urgency", 1), trg_id, trg))
    trigger_items.sort(key=lambda x: -x[0])

    for urgency, trg_id, trg in trigger_items:
        if len(actions) >= 20:
            break

        # Skip suppressed triggers
        suppression_key = trg.get("suppression_key", "")
        if suppression_key and suppression_key in _sent_suppressions:
            logger.info(f"Skipping suppressed trigger: {trg_id}")
            continue

        merchant_id = trg.get("merchant_id")
        customer_id = trg.get("customer_id")

        if not merchant_id:
            continue

        # Get all contexts
        trigger, merchant, category, customer = store.get_trigger_full(trg_id)
        if not merchant or not category:
            logger.warning(f"Missing merchant or category for trigger {trg_id}")
            continue

        # Skip if merchant already has an active conversation for this suppression_key
        # (prevents double-sending for same event)
        if conv_mgr.is_suppressed(suppression_key):
            continue

        # Generate a unique, meaningful conversation_id
        owner = merchant.get("identity", {}).get("owner_first_name", "m")
        kind = trg.get("kind", "msg")
        ts = body.now[:10].replace("-", "")
        conv_id = f"conv_{merchant_id[:20]}_{kind[:15]}_{ts}"

        # Ensure uniqueness if there's a collision
        base_conv_id = conv_id
        suffix = 0
        while conv_id in _active_conv_ids:
            suffix += 1
            conv_id = f"{base_conv_id}_{suffix}"

        try:
            composed = composer.compose(
                trigger=trigger,
                merchant=merchant,
                category=category,
                customer=customer,
                mode="compose",
            )
        except Exception as e:
            logger.error(f"Composer error for trigger {trg_id}: {e}")
            continue

        body_text = composed.get("body", "").strip()
        if not body_text:
            continue

        # Determine send_as
        is_customer_scope = trg.get("scope") == "customer" or customer is not None
        send_as = "merchant_on_behalf" if is_customer_scope else "vera"

        # Template params (first 3 meaningful tokens from body for WhatsApp template)
        identity = merchant.get("identity", {})
        template_params = _make_template_params(body_text, identity, trg)
        template_name = _get_template_name(trg.get("kind", "generic"), send_as)

        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trg_id,
            "template_name": template_name,
            "template_params": template_params,
            "body": body_text,
            "cta": composed.get("cta", "open_ended"),
            "suppression_key": suppression_key,
            "rationale": composed.get("rationale", ""),
        }

        actions.append(action)

        # Register the conversation
        conv_mgr.start(
            conversation_id=conv_id,
            merchant_id=merchant_id,
            trigger_id=trg_id,
            suppression_key=suppression_key,
            customer_id=customer_id,
            bot_body=body_text,
        )
        _active_conv_ids.add(conv_id)

        # Mark suppression key as used
        if suppression_key:
            _sent_suppressions.add(suppression_key)

        logger.info(f"Action queued: conv={conv_id} kind={trg.get('kind')} merchant={merchant_id}")

    return {"actions": actions}


# ---------------------------------------------------------------------------
# Reply — multi-turn handler
# ---------------------------------------------------------------------------

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: str = ""
    turn_number: int = 2


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    """
    Handle a merchant/customer reply and produce the bot's next move.
    Returns: {action: send|wait|end, body?, cta?, rationale}
    """
    conv_id = body.conversation_id
    merchant_id = body.merchant_id or ""
    message = body.message or ""

    # Load conversation
    conv = conv_mgr.get(conv_id)
    if not conv:
        # Unknown conversation — create a minimal one
        conv_mgr.start(
            conversation_id=conv_id,
            merchant_id=merchant_id,
            trigger_id="",
            suppression_key="",
        )
        conv = conv_mgr.get(conv_id)

    # Track turn in conversation history
    if conv:
        conv.turns.append({"turn": body.turn_number, "from": body.from_role, "msg": message})

    # Classify and route the reply
    decision = conv_mgr.process_reply(
        conversation_id=conv_id,
        merchant_id=merchant_id,
        message=message,
        turn_number=body.turn_number,
        bot_context={},
    )

    # If the decision requires a composed response, do it now
    if decision.get("_needs_compose"):
        mode = decision.get("mode", "engaged")
        response = _compose_reply(
            conv_id=conv_id,
            merchant_id=merchant_id,
            message=message,
            mode=mode,
            conv=conv,
        )
        return response

    # Otherwise return the decision directly (end/wait)
    action = decision.get("action", "end")
    result = {"action": action, "rationale": decision.get("rationale", "")}
    if action == "wait":
        result["wait_seconds"] = decision.get("wait_seconds", 14400)
    return result


def _compose_reply(
    conv_id: str,
    merchant_id: str,
    message: str,
    mode: str,
    conv,
) -> dict:
    """Compose a reply in context of an existing conversation."""
    # Load contexts
    merchant, category = store.get_merchant_with_category(merchant_id)

    if not merchant or not category:
        # No context — give a graceful generic reply
        return {
            "action": "send",
            "body": "Noted! Let me know what you'd like to work on next.",
            "cta": "open_ended",
            "rationale": "No context available; generic continuation.",
        }

    # Load trigger and customer
    trigger = {}
    customer = None
    if conv and conv.trigger_id:
        trigger = store.get("trigger", conv.trigger_id) or {}
    if conv and conv.customer_id:
        customer = store.get("customer", conv.customer_id)

    # If no trigger in store, build a minimal synthetic one for reply composition
    if not trigger:
        trigger = {
            "id": f"reply_{conv_id}",
            "kind": "active_planning_intent",
            "scope": "merchant",
            "source": "internal",
            "merchant_id": merchant_id,
            "payload": {"merchant_last_message": message},
            "urgency": 3,
            "suppression_key": "",
        }

    last_bot_body = conv.last_bot_body if conv else None

    try:
        composed = composer.compose(
            trigger=trigger,
            merchant=merchant,
            category=category,
            customer=customer,
            conversation_history=conv.turns if conv else None,
            mode=mode,
            merchant_last_message=message,
            last_bot_body=last_bot_body,
        )
    except Exception as e:
        logger.error(f"Composer error in reply: {e}")
        return {
            "action": "send",
            "body": "Got it! Let me work on that — give me a moment.",
            "cta": "open_ended",
            "rationale": "Fallback reply after composer error.",
        }

    body_text = composed.get("body", "").strip()
    if not body_text:
        return {
            "action": "end",
            "rationale": "Composed empty body; closing to avoid spam.",
        }

    # Anti-repetition guard
    if conv_mgr.is_repeated_body(conv_id, body_text):
        logger.warning(f"Repeated body detected for conv {conv_id}; adding variation")
        body_text = body_text + " (Koi sawaal ho to bataiye 🙂)"

    # Update last bot body
    conv_mgr.update_bot_body(conv_id, body_text)

    return {
        "action": "send",
        "body": body_text,
        "cta": composed.get("cta", "open_ended"),
        "rationale": composed.get("rationale", ""),
    }


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

@app.post("/v1/teardown")
async def teardown():
    """Wipe all in-memory state. Called by judge at end of test."""
    store.wipe()
    conv_mgr.wipe()
    _sent_suppressions.clear()
    _active_conv_ids.clear()
    logger.info("Teardown complete — all state wiped.")
    return {"wiped": True, "message": "State cleared."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_template_params(body: str, identity: dict, trigger: dict) -> list:
    """Extract meaningful template parameters for WhatsApp first-touch template."""
    name = identity.get("owner_first_name") or identity.get("name", "Merchant")
    kind = trigger.get("kind", "update")

    # Truncate body to a useful snippet
    words = body.split()
    snippet = " ".join(words[:12]) + ("..." if len(words) > 12 else "")

    return [name, kind.replace("_", " ").title(), snippet]


def _get_template_name(kind: str, send_as: str) -> str:
    """Return a sensible WhatsApp template name for the trigger kind."""
    prefix = "merchant" if send_as == "merchant_on_behalf" else "vera"
    kind_slug = kind.replace("_", "_")[:25]
    return f"{prefix}_{kind_slug}_v1"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
