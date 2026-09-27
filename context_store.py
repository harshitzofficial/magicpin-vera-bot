"""
context_store.py — Versioned, idempotent in-memory context store.

Stores category, merchant, customer, and trigger contexts.
Semantics:
  - Accept if version > current_version  →  200
  - Reject if version <= current_version →  409
  - Exact same version re-push            →  409 (stale)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


class ContextStore:
    """Thread-safe, versioned in-memory context store."""

    VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

    def __init__(self):
        self._lock = threading.Lock()
        # (scope, context_id) -> {"version": int, "payload": dict, "stored_at": str}
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def push(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: dict,
    ) -> Tuple[bool, Optional[int], str]:
        """
        Store or reject a context push.

        Returns:
            (accepted: bool, current_version: int | None, ack_id: str)
        """
        if scope not in self.VALID_SCOPES:
            return False, None, f"invalid_scope:{scope}"

        key = (scope, context_id)
        stored_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            existing = self._store.get(key)
            if existing and existing["version"] >= version:
                return False, existing["version"], "stale_version"

            self._store[key] = {
                "version": version,
                "payload": payload,
                "stored_at": stored_at,
            }

        ack_id = f"ack_{context_id}_v{version}"
        return True, None, ack_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        """Return payload for (scope, context_id) or None."""
        key = (scope, context_id)
        with self._lock:
            entry = self._store.get(key)
            return entry["payload"] if entry else None

    def get_all(self, scope: str) -> Dict[str, dict]:
        """Return {context_id: payload} for all entries of a scope."""
        with self._lock:
            return {
                cid: entry["payload"]
                for (s, cid), entry in self._store.items()
                if s == scope
            }

    def counts(self) -> Dict[str, int]:
        """Return count per scope — used by /v1/healthz."""
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        with self._lock:
            for (scope, _) in self._store:
                if scope in counts:
                    counts[scope] += 1
        return counts

    # ------------------------------------------------------------------
    # Wipe (teardown)
    # ------------------------------------------------------------------

    def wipe(self):
        """Wipe all stored contexts. Called on /v1/teardown."""
        with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_merchant_with_category(
        self, merchant_id: str
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """Convenience: return (merchant_payload, category_payload) or (None, None)."""
        merchant = self.get("merchant", merchant_id)
        if not merchant:
            return None, None
        cat_slug = merchant.get("category_slug", "")
        category = self.get("category", cat_slug)
        return merchant, category

    def get_trigger_full(
        self, trigger_id: str
    ) -> Tuple[Optional[dict], Optional[dict], Optional[dict], Optional[dict]]:
        """
        Return (trigger, merchant, category, customer) for a trigger_id.
        Any missing piece returns None.
        """
        trigger = self.get("trigger", trigger_id)
        if not trigger:
            return None, None, None, None

        merchant_id = trigger.get("merchant_id")
        customer_id = trigger.get("customer_id")

        merchant, category = self.get_merchant_with_category(merchant_id) if merchant_id else (None, None)
        customer = self.get("customer", customer_id) if customer_id else None

        return trigger, merchant, category, customer
