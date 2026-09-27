"""
prompts.py — Per-trigger-kind + per-category prompt templates for the Vera composer.

Every compose call gets:
  1. A system prompt (Vera persona + category voice rules + anti-patterns)
  2. A user prompt (structured context + trigger-kind framing hint)
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Category voice rules (enforced in system prompt)
# ---------------------------------------------------------------------------

CATEGORY_VOICE = {
    "dentists": {
        "tone": "peer-to-peer clinical (you are a knowledgeable colleague, not a salesperson)",
        "salutation": "Dr. {owner_first_name}",
        "vocab_examples": "fluoride varnish, scaling, caries, OPG, IOPA, RCT, bruxism, endodontic, periodontal",
        "taboos": "guaranteed, cure, 100% safe, miracle, best in city, doctor approved",
        "cta_note": "Never promotional. Cite research/compliance sources by name.",
    },
    "salons": {
        "tone": "warm, practical, fellow-operator (friend who knows beauty trends)",
        "salutation": "Hi {owner_first_name}",
        "vocab_examples": "balayage, keratin, olaplex, wella, highlights, hair spa, manicure, bridal trial",
        "taboos": "guaranteed glow, permanent results, instant transformation, miracle, best in city",
        "cta_note": "Warm and friendly. Use emojis sparingly. Focus on seasonal demand and client retention.",
    },
    "restaurants": {
        "tone": "warm busy practical (fellow operator, short on time)",
        "salutation": "Hi {owner_first_name}",
        "vocab_examples": "covers, AOV, footfall, table turnover, thali, reservations, weekend brunch",
        "taboos": "guaranteed packed house, miracle marketing, viral guarantee, best food in city",
        "cta_note": "Operator-to-operator voice. Use real data (orders, covers, trends).",
    },
    "gyms": {
        "tone": "energetic but disciplined (coach to gym owner)",
        "salutation": "Hi {owner_first_name}",
        "vocab_examples": "PT sessions, membership churn, 1RM, HIIT, footfall, trial-to-paid, bulk, cut",
        "taboos": "guaranteed weight loss, shred in 7 days, miracle transformation, fastest results",
        "cta_note": "Motivational but data-grounded. Seasonal awareness (Apr-Jun = low acquisition).",
    },
    "pharmacies": {
        "tone": "trustworthy, precise, neighbourhood pharmacist",
        "salutation": "Hi {owner_first_name}",
        "vocab_examples": "OTC, schedule H, molecule, MRP, batch, generic, branded, chronic Rx, PCR retail",
        "taboos": "miracle cure, guaranteed result, 100% safe, doctor recommended (without disclosure)",
        "cta_note": "Regulatory accuracy is paramount. Cite CDSCO/FDA circulars by name and date.",
    },
}

# ---------------------------------------------------------------------------
# Trigger-kind framing hints (embedded in user prompt)
# ---------------------------------------------------------------------------

KIND_FRAMING = {
    "research_digest": (
        "Frame this as a valuable clinical/industry finding from a named source. "
        "Lead with the most merchant-relevant stat. Offer to do the work for them (pull abstract, draft patient post). "
        "CTA: open_ended (no forced binary)."
    ),
    "regulation_change": (
        "Frame as a compliance heads-up with a concrete deadline. "
        "State the exact rule change, what changes, and the action required. "
        "Offer to help with the audit/SOP update. CTA: binary_yes_no."
    ),
    "cde_opportunity": (
        "Professional development framing. Mention credits, fee, date. "
        "Keep it short — one ask. CTA: binary_yes_no."
    ),
    "perf_spike": (
        "Positive momentum. Reference the exact metric that spiked and the percentage. "
        "Suggest amplifying the driver (post, offer, follow-up). CTA: open_ended."
    ),
    "perf_dip": (
        "Reframe as an opportunity, not a crisis. Use exact metric + delta. "
        "Propose one actionable step. CTA: open_ended."
    ),
    "seasonal_perf_dip": (
        "Normalize the dip using category seasonal data. Pivot to retention over acquisition. "
        "Propose a retention engagement (challenge, offer, follow-up). CTA: open_ended."
    ),
    "milestone_reached": (
        "Celebrate briefly, then pivot to the next milestone or action. "
        "Keep it short and energizing. CTA: open_ended."
    ),
    "dormant_with_vera": (
        "Re-engagement with curiosity. Something new happened (digest, trend, metric) that's worth sharing. "
        "Don't mention dormancy explicitly. CTA: binary_yes_no."
    ),
    "winback_eligible": (
        "Loss aversion + easy re-entry. Reference what they're missing since expiry (lapsed customers, lost views). "
        "Make the ask as frictionless as possible. CTA: binary_yes_no."
    ),
    "renewal_due": (
        "Urgency + value anchor. State days remaining and what's at stake (profile goes dark, leads stop). "
        "CTA: binary_yes_no."
    ),
    "festival_upcoming": (
        "Seasonal opportunity framing. Reference the festival, days until, and category-relevant angle. "
        "Propose a specific action (post, offer, package). CTA: open_ended."
    ),
    "ipl_match_today": (
        "Real-time data insight. Be specific (match, venue, time). "
        "Add judgment — Saturday IPL = -12% covers, weeknight = +18%. Recommend accordingly. "
        "CTA: binary_yes_no."
    ),
    "category_seasonal": (
        "Demand shift. Lead with the highest-impact trend (e.g., ORS +40%, cold/cough -60%). "
        "Recommend a shelf/stock action. CTA: binary_yes_no."
    ),
    "supply_alert": (
        "Urgent compliance action. Lead with molecule/batch, risk framing (sub-potency, no safety risk), "
        "then count of affected customers from their roster. "
        "Offer to draft the customer WhatsApp. CTA: binary_yes_no."
    ),
    "gbp_unverified": (
        "Loss aversion. State the estimated uplift from verification (30%+ views). "
        "Make the path clear (postcard or phone call). CTA: binary_yes_no."
    ),
    "review_theme_emerged": (
        "Social proof (positive theme) or fix opportunity (negative theme). "
        "Quote the theme with occurrence count. Offer a concrete next step. CTA: open_ended."
    ),
    "competitor_opened": (
        "Voyeur-curiosity. Name the competitor, distance, and their offer if known. "
        "Frame as 'you should know' (reciprocity). Suggest a counter-action. CTA: open_ended."
    ),
    "curious_ask_due": (
        "Asking-the-merchant lever. One simple question about their business right now. "
        "Offer reciprocity up-front (I'll turn the answer into X). CTA: open_ended."
    ),
    "active_planning_intent": (
        "The merchant asked for this or signalled interest. EXECUTE, don't qualify further. "
        "Draft the artifact they requested (package, post, plan). Present it, then ask for confirmation. "
        "CTA: binary_confirm_cancel."
    ),
    # Customer-scoped triggers (send_as = merchant_on_behalf)
    "recall_due": (
        "Customer-facing. Send as merchant. Use the customer's name and language pref. "
        "State how many months since last visit, that the recall window is open. "
        "Offer 2 specific slots (from trigger payload). State the price. "
        "CTA: multi_choice_slot (Reply 1 for Wed, 2 for Thu)."
    ),
    "chronic_refill_due": (
        "Customer-facing refill dispatch. List molecules, run-out date, total with discounts. "
        "Confirm delivery address. CTA: binary_confirm_cancel (Reply CONFIRM)."
    ),
    "customer_lapsed_soft": (
        "Warm, no-shame winback. Reference time since last visit without guilt-tripping. "
        "Mention something new (class, offer, slot) that matches their past preference. "
        "CTA: binary_yes_no."
    ),
    "customer_lapsed_hard": (
        "No-shame, fresh-start winback. Don't mention how long it's been. "
        "Lead with a new offer or program that fits their previous training focus. "
        "Binary, low-commitment CTA."
    ),
    "trial_followup": (
        "Low-friction next booking. Reference their trial date. "
        "Offer the next slot. Make it easy. CTA: binary_yes_no."
    ),
    "wedding_package_followup": (
        "Urgency from days-to-wedding countdown. Reference the trial they did. "
        "Open the skin-prep/package window. One slot ask. CTA: binary_yes_no."
    ),
    "appointment_tomorrow": (
        "Confirmation + micro-prep tip. State appointment time, service, price if applicable. "
        "One friendly tip (arrive 5 min early, bring previous prescription, etc.). CTA: binary_yes_no."
    ),
}

_DEFAULT_FRAMING = (
    "Compose a relevant, specific, engaging message using the context provided. "
    "Ground every claim in the data given. CTA should match the trigger urgency."
)

# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_system_prompt(category_slug: str, is_customer_facing: bool = False) -> str:
    voice = CATEGORY_VOICE.get(category_slug, {
        "tone": "friendly professional",
        "salutation": "Hi {owner_first_name}",
        "vocab_examples": "general business terms",
        "taboos": "guaranteed, miracle, best in city",
        "cta_note": "Be specific and actionable.",
    })

    facing = "a customer of the merchant" if is_customer_facing else "the merchant"

    return f"""You are Vera, magicpin's merchant AI assistant. You compose WhatsApp messages for {facing}.

PERSONA:
- You are a knowledgeable, collegial assistant — not a salesperson
- Tone: {voice['tone']}
- Salutation style: {voice['salutation']}
- Domain vocabulary to use naturally: {voice['vocab_examples']}
- NEVER use these words/phrases: {voice['taboos']}
- {voice['cta_note']}

GOLDEN RULES (violation = score penalty):
1. SPECIFICITY: Every message must anchor on at least one verifiable fact from the context (number, date, percentage, source name, page reference). Generic "increase your sales" type statements are BANNED.
2. NO FABRICATION: Only use data explicitly present in the provided context. Never invent percentages, citations, competitor names, batch numbers, or slot times.
3. SINGLE CTA: One clear call-to-action in the LAST sentence. Never bury it. Never give 3 options when 1 will do (except booking flows).
4. NO URLS: Never include URLs or links. Meta will reject them. Describe content instead.
5. NO PREAMBLES: Never open with "I hope you're doing well" or "I'm reaching out to". Start with the value immediately.
6. NO RE-INTRODUCTION: Never say "I'm Vera" in a follow-up message. Only in the first touch.
7. LANGUAGE MATCH: If the merchant/customer prefers hi-en mix, use Hindi-English code-mix naturally (not forced).
8. NO REPETITION: Never repeat the same message body you sent before in this conversation.
9. VOICE MATCH: Clinical/peer tone for dentists and pharmacies. Warm-practical for salons. Operator-to-operator for restaurants. Coach-to-owner for gyms.
10. CTA PLACEMENT: The call-to-action must be in the final line of the message.

OUTPUT FORMAT (return ONLY valid JSON, no markdown wrapper):
{{
  "body": "<the WhatsApp message text, max ~300 chars for punchy messages>",
  "cta": "<one of: open_ended | binary_yes_no | binary_confirm_cancel | multi_choice_slot | none>",
  "rationale": "<2-3 sentences: why this message, what compulsion levers used, why this CTA>"
}}"""


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------

def build_user_prompt(
    trigger: dict,
    merchant: dict,
    category: dict,
    customer: Optional[dict] = None,
    conversation_history: Optional[list] = None,
    mode: str = "compose",  # "compose" | "action" | "engaged"
    merchant_last_message: Optional[str] = None,
) -> str:
    kind = trigger.get("kind", "unknown")
    framing = KIND_FRAMING.get(kind, _DEFAULT_FRAMING)

    # Build context sections
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    sub = merchant.get("subscription", {})
    offers = merchant.get("offers", [])
    signals = merchant.get("signals", [])
    review_themes = merchant.get("review_themes", [])
    cust_agg = merchant.get("customer_aggregate", {})
    conv_hist = merchant.get("conversation_history", [])
    peer = category.get("peer_stats", {})
    digest = category.get("digest", [])
    seasonal = category.get("seasonal_beats", [])
    offer_catalog = category.get("offer_catalog", [])

    active_offers = [o for o in offers if o.get("status") == "active"]
    expired_offers = [o for o in offers if o.get("status") == "expired"]

    # Resolve digest item if trigger references one
    trigger_payload = trigger.get("payload", {})
    top_item_id = trigger_payload.get("top_item_id") or trigger_payload.get("alert_id")
    relevant_digest = None
    if top_item_id:
        for d in digest:
            if d.get("id") == top_item_id:
                relevant_digest = d
                break
    # Also include all digest if no specific item
    if not relevant_digest and digest:
        relevant_digest = digest[0]  # fallback to most recent

    # Customer section
    cust_section = ""
    if customer:
        cid = customer.get("identity", {})
        rel = customer.get("relationship", {})
        prefs = customer.get("preferences", {})
        cust_section = f"""
CUSTOMER (message on behalf of merchant to this customer):
  Name: {cid.get('name', 'Customer')}
  Language pref: {cid.get('language_pref', 'english')}
  Age band: {cid.get('age_band', 'unknown')}
  State: {customer.get('state', 'unknown')}
  Last visit: {rel.get('last_visit', 'unknown')}
  Visits total: {rel.get('visits_total', 0)}
  Services received: {rel.get('services_received', [])}
  Preferred slots: {prefs.get('preferred_slots', 'not specified')}
  Consent scope: {customer.get('consent', {}).get('scope', [])}"""

    # Conversation history section
    hist_section = ""
    if conversation_history:
        hist_section = "\nCONVERSATION SO FAR:\n"
        for turn in conversation_history[-4:]:  # last 4 turns
            role = turn.get("from", "?")
            msg = turn.get("body") or turn.get("msg", "")
            hist_section += f"  [{role}]: {msg}\n"
    elif conv_hist:
        hist_section = "\nPAST VERA INTERACTIONS:\n"
        for h in conv_hist[-2:]:
            hist_section += f"  [{h.get('from', '?')}]: {h.get('body', '')[:120]}\n"

    # Mode-specific instruction
    if mode == "action":
        mode_instr = (
            f"\n⚡ MERCHANT COMMITTED: They said '{merchant_last_message}'. "
            "SWITCH TO ACTION MODE immediately. Do NOT ask qualifying questions. "
            "Execute what was promised. Draft the artifact. Present it. Ask for final confirm."
        )
    elif mode == "engaged":
        mode_instr = (
            f"\n💬 MERCHANT REPLIED: '{merchant_last_message}'. "
            "Continue the conversation naturally. Advance toward value delivery."
        )
    else:
        mode_instr = f"\n📋 TRIGGER FRAMING GUIDE: {framing}"

    return f"""COMPOSE A WHATSAPP MESSAGE for the following context:

=== TRIGGER ===
Kind: {kind}
Source: {trigger.get('source', 'unknown')}
Scope: {trigger.get('scope', 'merchant')}
Urgency: {trigger.get('urgency', 1)}/5
Payload: {trigger_payload}

=== RELEVANT DIGEST/ALERT ITEM ===
{_format_digest(relevant_digest)}

=== CATEGORY ===
Slug: {category.get('slug', 'unknown')}
Offer catalog (use these formats, not generic discounts): {[o.get('title') for o in offer_catalog[:5]]}
Peer stats: avg_ctr={peer.get('avg_ctr', '?')}, avg_views_30d={peer.get('avg_views_30d', '?')}, avg_calls_30d={peer.get('avg_calls_30d', '?')}
Seasonal beats: {[f"{s.get('month_range')}: {s.get('note')}" for s in seasonal[:3]]}

=== MERCHANT ===
Name: {identity.get('name', 'Merchant')}
Owner first name: {identity.get('owner_first_name', 'Owner')}
Locality: {identity.get('locality', '?')}, {identity.get('city', '?')}
Verified: {identity.get('verified', False)}
Languages: {identity.get('languages', ['en'])}
Subscription: {sub.get('status', '?')}, plan={sub.get('plan', '?')}, days_remaining={sub.get('days_remaining', '?')}
Performance (30d): views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, directions={perf.get('directions', '?')}, ctr={perf.get('ctr', '?')}
  vs peer avg_ctr={peer.get('avg_ctr', '?')} → {"BELOW" if (perf.get('ctr', 0) or 0) < (peer.get('avg_ctr', 0) or 0) else "above"} peer median
Performance delta (7d): {perf.get('delta_7d', {})}
Active offers: {[o.get('title') for o in active_offers] or 'none'}
Expired offers: {[o.get('title') for o in expired_offers] or 'none'}
Signals: {signals}
Review themes: {[f"{r.get('theme')} ({r.get('sentiment')}, {r.get('occurrences_30d')}x)" for r in review_themes]}
Customer aggregate: {cust_agg}
{cust_section}
{hist_section}
{mode_instr}

IMPORTANT REMINDERS:
- Do NOT include any URLs in the body
- Use owner's first name: {identity.get('owner_first_name', 'Owner')}
- Category voice: {CATEGORY_VOICE.get(category.get('slug', ''), {}).get('tone', 'professional')}
- If languages include 'hi', use natural Hindi-English mix
- Ground every claim in the data above. If a specific number isn't in the data, don't invent it.
- {"Send as merchant_on_behalf (from merchant to their customer)" if customer else "Send as vera (from Vera to merchant)"}

Return ONLY the JSON object with body, cta, and rationale fields."""


def _format_digest(item: Optional[dict]) -> str:
    if not item:
        return "No specific digest item for this trigger."
    return (
        f"  ID: {item.get('id', '?')}\n"
        f"  Title: {item.get('title', '?')}\n"
        f"  Source: {item.get('source', '?')}\n"
        f"  Summary: {item.get('summary', '?')}\n"
        f"  Actionable: {item.get('actionable', '?')}\n"
        f"  Trial N: {item.get('trial_n', 'N/A')}\n"
        f"  Patient segment: {item.get('patient_segment', 'N/A')}"
    )
