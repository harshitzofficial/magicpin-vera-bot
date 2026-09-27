# Vera — magicpin AI Challenge Submission

## Approach

**Architecture**: A stateful FastAPI server implementing all 6 judge endpoints. Composition is powered by Google Gemini 1.5 Flash (temperature=0 for determinism) with per-trigger-kind prompt dispatch and per-category voice injection.

### Four-layer composition pipeline

```
TriggerContext + MerchantContext + CategoryContext + CustomerContext?
    ↓
Trigger-kind dispatcher (26 trigger types → tailored prompt framing)
    ↓
Category voice injector (tone, vocab, taboos per category slug)
    ↓
Gemini 1.5 Flash (temp=0) → {body, cta, rationale}
    ↓
Post-LLM validator (URL strip, taboo check, CTA normalize, repetition guard)
```

### Key design decisions

1. **Per-trigger-kind prompts** — Each of 26 trigger types gets a specific framing hint (e.g. `research_digest` → source-citation framing; `active_planning_intent` → execute immediately, don't qualify).

2. **Category voice injection** — Every system prompt enforces the exact vocabulary, taboos, tone, and salutation style from `categories/*.json`. Dentists get peer-clinical. Restaurants get operator-to-operator. Pharmacies get trustworthy-precise.

3. **Conversation state machine** — 5 states: `initiated → engaged → action_mode → completed | exited`. Auto-reply pattern matching (15+ patterns) with escalating backoff (try once → wait 4h → end). Commitment detection in English and Hindi.

4. **Anti-pattern validation** — Post-LLM pass strips URLs, catches taboo words, normalizes CTAs, detects repetition, and flags preambles.

5. **Suppression-key dedup** — Each tick checks `_sent_suppressions` before composing; no trigger fires twice.

6. **Contextual specificity** — Prompts inject: peer stats (CTR comparison), merchant performance delta, `digest[].actionable` fields, `review_themes`, `seasonal_beats`, and `signals` to ensure every message anchors on verifiable data.

### Compulsion levers used

- **Social proof**: peer CTR comparison ("your CTR is 2.1% vs peer avg 3.0%")
- **Asking the merchant**: `curious_ask_due` trigger → "what's been most in demand this week?"
- **Effort externalization**: "I've drafted X — just say go"
- **Loss aversion**: winback/renewal/gbp-unverified framing
- **Source citations**: JIDA, DCI, CDSCO, magicpin data — always cited by name

### What additional context would have helped most

1. **Real slot availability** — The triggers include `available_slots` but these are fabricated. Real calendar integration would make recall/appointment messages far more accurate.
2. **Merchant conversation history from production** — The `conversation_history` field in seeds is minimal. Real 7-turn histories would let the bot avoid repeating themes.
3. **Category-specific peer stats at the locality level** — "Your CTR vs Lajpat Nagar dentists" is stronger than "vs metro solo practices."

## Files

| File | Purpose |
|---|---|
| `bot.py` | FastAPI server (6 endpoints) |
| `composer.py` | Gemini 1.5 Flash composition engine |
| `context_store.py` | Versioned, idempotent in-memory store |
| `conversation_manager.py` | State machine + auto-reply + intent detection |
| `prompts.py` | Per-kind + per-category prompt templates |
| `validators.py` | Post-LLM validation |
| `generate_submission.py` | Generate submission.jsonl from test_pairs |
| `submission.jsonl` | 30 pre-generated test pair compositions |

## Running locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Gemini API key
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here

# 3. Start the server
uvicorn bot:app --host 0.0.0.0 --port 8080

# 4. Run the judge simulator (in another terminal)
export BOT_URL=http://localhost:8080
python judge_simulator.py

# 5. Generate submission.jsonl
python generate_submission.py
```
