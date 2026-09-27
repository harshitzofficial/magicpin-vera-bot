"""
conversation_manager.py — Conversation state machine.

Tracks active conversations, detects auto-replies, classifies merchant intent,
and enforces graceful exit rules.

State machine:
  [initiated] → [engaged] → [action_mode] → [completed | exited]
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ConvState(str, Enum):
    INITIATED  = "initiated"   # bot sent first message, awaiting reply
    ENGAGED    = "engaged"     # merchant replied (real reply, not auto)
    ACTION     = "action_mode" # merchant committed, bot is executing
    COMPLETED  = "completed"   # successful outcome
    EXITED     = "exited"      # graceful exit (hostile, not-interested, auto-reply timeout)


# ---------------------------------------------------------------------------
# Auto-reply patterns
# ---------------------------------------------------------------------------

_AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thanks for (contacting|reaching out)",
    r"our team will (respond|get back)",
    r"this is an (automated|auto)",
    r"i am an? automated",
    r"we will respond (shortly|soon|within)",
    r"away (from|on) (vacation|leave|holiday)",
    r"out of (office|town|reach)",
    r"will reply (shortly|soon|later)",
    r"currently (unavailable|offline|away)",
    r"bahut.{0,10}shukriya.{0,30}(team|pahuncha|jaankari)",  # Hindi auto-reply pattern from brief
    r"main ek automated",
]

_AUTO_REPLY_RE = re.compile(
    "|".join(_AUTO_REPLY_PATTERNS),
    re.IGNORECASE | re.DOTALL,
)

# ---------------------------------------------------------------------------
# Intent commitment signals
# ---------------------------------------------------------------------------

_COMMIT_WORDS_EN = [
    r"\byes\b", r"\bgo ahead\b", r"\blet'?s do it\b", r"\bconfirm\b",
    r"\bproceed\b", r"\bsend it\b", r"\bdo it\b", r"\bokay\b", r"\bok\b",
    r"\bsure\b", r"\babsolutely\b", r"\bgreat\b", r"\bsounds good\b",
    r"\bwhat'?s next\b", r"\bnext steps?\b", r"\bhow do we start\b",
]
_COMMIT_WORDS_HI = [
    r"\bhaan\b", r"\bha\b", r"\bji haan\b", r"\bchalte hain\b",
    r"\bkaro\b", r"\bkar do\b", r"\btheek hai\b", r"\bbilkul\b",
    r"\baage badho\b", r"\bshuru karo\b",
]
_COMMIT_RE = re.compile(
    "|".join(_COMMIT_WORDS_EN + _COMMIT_WORDS_HI),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Hostile / opt-out signals
# ---------------------------------------------------------------------------

_HOSTILE_PATTERNS = [
    r"\bstop\b", r"\bopt.?out\b", r"\bunsubscribe\b",
    r"\bnot interested\b", r"\bdon'?t (contact|message|call|bother)\b",
    r"\bstop messaging\b", r"\bstop (calling|texting|whatsapp)\b",
    r"\bplease remove\b", r"\bblock\b",
    r"\bbakwas\b", r"\bband karo\b", r"\bmat karo\b", r"\bchup\b",
    r"\bnahi chahiye\b", r"\bmat bhejo\b",
    r"useless", r"spam", r"irritating", r"annoying",
]
_HOSTILE_RE = re.compile(
    "|".join(_HOSTILE_PATTERNS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Conversation dataclass
# ---------------------------------------------------------------------------

@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    state: ConvState = ConvState.INITIATED
    suppression_key: Optional[str] = None

    # Message history for this conversation
    turns: List[Dict] = field(default_factory=list)

    # Auto-reply tracking
    auto_reply_count: int = 0
    last_merchant_messages: List[str] = field(default_factory=list)

    # Body of the last message sent by the bot (for anti-repetition check)
    last_bot_body: Optional[str] = None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ConversationManager:
    """Thread-safe conversation tracker and intent classifier."""

    def __init__(self):
        self._lock = threading.Lock()
        self._convs: Dict[str, Conversation] = {}
        # suppression_key -> conversation_id (dedup guard)
        self._suppressed: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        conversation_id: str,
        merchant_id: str,
        trigger_id: str,
        suppression_key: str,
        customer_id: Optional[str] = None,
        bot_body: Optional[str] = None,
    ) -> bool:
        """
        Register a new conversation. Returns False if conversation_id already exists.
        """
        with self._lock:
            if conversation_id in self._convs:
                return False  # already exists; use /v1/reply instead

            conv = Conversation(
                conversation_id=conversation_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                trigger_id=trigger_id,
                state=ConvState.INITIATED,
                suppression_key=suppression_key,
                last_bot_body=bot_body,
            )
            self._convs[conversation_id] = conv
            if suppression_key:
                self._suppressed[suppression_key] = conversation_id
            return True

    def get(self, conversation_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._convs.get(conversation_id)

    def is_suppressed(self, suppression_key: str) -> bool:
        """Check if a suppression key was already used (dedup)."""
        with self._lock:
            return suppression_key in self._suppressed

    def is_active(self, conversation_id: str) -> bool:
        with self._lock:
            conv = self._convs.get(conversation_id)
            return conv is not None and conv.state not in (
                ConvState.COMPLETED, ConvState.EXITED
            )

    def mark_exited(self, conversation_id: str):
        with self._lock:
            conv = self._convs.get(conversation_id)
            if conv:
                conv.state = ConvState.EXITED

    def mark_completed(self, conversation_id: str):
        with self._lock:
            conv = self._convs.get(conversation_id)
            if conv:
                conv.state = ConvState.COMPLETED

    def update_bot_body(self, conversation_id: str, body: str):
        with self._lock:
            conv = self._convs.get(conversation_id)
            if conv:
                conv.last_bot_body = body

    def wipe(self):
        with self._lock:
            self._convs.clear()
            self._suppressed.clear()

    # ------------------------------------------------------------------
    # Message classification
    # ------------------------------------------------------------------

    @staticmethod
    def is_auto_reply(message: str) -> bool:
        """Return True if message matches known auto-reply patterns."""
        return bool(_AUTO_REPLY_RE.search(message))

    @staticmethod
    def is_commit(message: str) -> bool:
        """Return True if merchant is making an explicit commitment."""
        return bool(_COMMIT_RE.search(message))

    @staticmethod
    def is_hostile(message: str) -> bool:
        """Return True if merchant is hostile or opting out."""
        return bool(_HOSTILE_RE.search(message))

    # ------------------------------------------------------------------
    # Reply decision logic
    # ------------------------------------------------------------------

    def process_reply(
        self,
        conversation_id: str,
        merchant_id: str,
        message: str,
        turn_number: int,
        bot_context: dict,  # trigger, merchant, category, customer payloads
    ) -> Dict:
        """
        Process a merchant reply and return the bot's next action dict.

        Returns one of:
          {"action": "send", "body": ..., "cta": ..., "rationale": ...}
          {"action": "wait", "wait_seconds": ..., "rationale": ...}
          {"action": "end",  "rationale": ...}
        """
        conv = self.get(conversation_id)
        if not conv:
            # Unknown conversation — treat as new engagement
            conv = Conversation(
                conversation_id=conversation_id,
                merchant_id=merchant_id,
            )
            with self._lock:
                self._convs[conversation_id] = conv

        # Record this merchant turn
        with self._lock:
            conv.turns.append({"turn": turn_number, "from": "merchant", "msg": message})

        # --- Priority 1: hostile / opt-out ---
        if self.is_hostile(message):
            self.mark_exited(conversation_id)
            return {
                "action": "end",
                "rationale": (
                    "Merchant signalled hostility or opted out. "
                    "Conversation closed; suppressing this merchant for 30 days."
                ),
            }

        # --- Priority 2: auto-reply detection ---
        if self.is_auto_reply(message):
            with self._lock:
                conv.auto_reply_count += 1
                conv.last_merchant_messages.append(message)
                count = conv.auto_reply_count

            if count == 1:
                # First auto-reply: send one nudge prompting the owner
                return {
                    "action": "send",
                    "body": (
                        "Looks like an auto-reply 😊 Jab owner/manager dekhe, "
                        "bas 'YES' reply karein — main kaam shuru kar deta/deti hoon."
                    ),
                    "cta": "binary_yes_no",
                    "rationale": (
                        "Detected canned auto-reply (turn 1). "
                        "One nudge directed at the real owner; keeping low friction."
                    ),
                }
            elif count == 2:
                # Second auto-reply: back off 4 hours
                return {
                    "action": "wait",
                    "wait_seconds": 14400,
                    "rationale": (
                        "Same auto-reply pattern twice in a row. "
                        "Owner not at phone; backing off 4 hours before retry."
                    ),
                }
            else:
                # Third+ auto-reply: exit
                self.mark_exited(conversation_id)
                return {
                    "action": "end",
                    "rationale": (
                        f"Auto-reply detected {count} times consecutively. "
                        "No real engagement; closing conversation."
                    ),
                }

        # --- Priority 3: commitment / intent transition ---
        if self.is_commit(message):
            with self._lock:
                conv.state = ConvState.ACTION

            # Delegate to composer for action-mode response
            return {"_needs_compose": True, "mode": "action", "conv": conv}

        # --- Priority 4: genuine reply — continue conversation ---
        with self._lock:
            conv.state = ConvState.ENGAGED

        return {"_needs_compose": True, "mode": "engaged", "conv": conv}

    # ------------------------------------------------------------------
    # Anti-repetition guard
    # ------------------------------------------------------------------

    def is_repeated_body(self, conversation_id: str, new_body: str) -> bool:
        """Return True if new_body is identical to the last bot message."""
        with self._lock:
            conv = self._convs.get(conversation_id)
            if not conv:
                return False
            return conv.last_bot_body == new_body

    def active_conversations_for_merchant(self, merchant_id: str) -> List[str]:
        """Return list of active conversation_ids for a merchant."""
        with self._lock:
            return [
                cid for cid, c in self._convs.items()
                if c.merchant_id == merchant_id
                and c.state not in (ConvState.COMPLETED, ConvState.EXITED)
            ]
