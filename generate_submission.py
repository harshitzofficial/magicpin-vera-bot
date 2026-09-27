"""
generate_submission.py — Generate the 30-pair submission.jsonl file.

This script:
1. Runs generate_dataset.py to expand the seed data
2. Picks the canonical 30 test pairs
3. Runs the composer on each pair
4. Writes submission.jsonl

Usage:
    python generate_submission.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Add current dir to path
sys.path.insert(0, str(Path(__file__).parent))

from composer import Composer

DATASET_DIR = Path(__file__).parent / "dataset"
EXPANDED_DIR = Path(__file__).parent / "dataset" / "expanded"
SUBMISSION_FILE = Path(__file__).parent / "submission.jsonl"


def load_expanded_dataset():
    """Load expanded dataset from ./dataset/expanded/ (run generate_dataset.py first)."""
    categories = {}
    merchants = {}
    customers = {}
    triggers = {}
    test_pairs = []

    # Categories
    cat_dir = EXPANDED_DIR / "categories"
    if cat_dir.exists():
        for f in cat_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            categories[data["slug"]] = data

    # Merchants
    merch_dir = EXPANDED_DIR / "merchants"
    if merch_dir.exists():
        for f in merch_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            merchants[data["merchant_id"]] = data

    # Customers
    cust_dir = EXPANDED_DIR / "customers"
    if cust_dir.exists():
        for f in cust_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            customers[data["customer_id"]] = data

    # Triggers
    trg_dir = EXPANDED_DIR / "triggers"
    if trg_dir.exists():
        for f in trg_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            triggers[data["id"]] = data

    # Test pairs
    tp_file = EXPANDED_DIR / "test_pairs.json"
    if tp_file.exists():
        test_pairs = json.loads(tp_file.read_text(encoding="utf-8"))["pairs"]

    return categories, merchants, customers, triggers, test_pairs


def run_generate_dataset():
    """Run the dataset generator if expanded dir doesn't exist."""
    if EXPANDED_DIR.exists() and (EXPANDED_DIR / "test_pairs.json").exists():
        print("Expanded dataset already exists. Skipping generation.")
        return

    print("Generating expanded dataset...")
    result = subprocess.run(
        [sys.executable, str(DATASET_DIR / "generate_dataset.py"),
         "--seed-dir", str(DATASET_DIR),
         "--out", str(EXPANDED_DIR)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Dataset generation failed:\n{result.stderr}")
        sys.exit(1)
    print(result.stdout)


def main():
    # Step 1: Expand dataset
    run_generate_dataset()

    # Step 2: Load
    categories, merchants, customers, triggers, test_pairs = load_expanded_dataset()
    print(f"Loaded: {len(categories)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers, {len(test_pairs)} test pairs")

    if not test_pairs:
        print("ERROR: No test pairs found. Check that generate_dataset.py ran correctly.")
        sys.exit(1)

    # Step 3: Compose
    comp = Composer()
    lines = []

    for i, pair in enumerate(test_pairs[:30]):
        test_id = pair.get("test_id", f"T{i+1:02d}")
        trigger_id = pair.get("trigger_id")
        merchant_id = pair.get("merchant_id")
        customer_id = pair.get("customer_id")

        print(f"[{i+1}/30] Composing {test_id}: trigger={trigger_id} merchant={merchant_id}")

        trigger = triggers.get(trigger_id, {})
        merchant = merchants.get(merchant_id, {})
        cat_slug = merchant.get("category_slug", "")
        category = categories.get(cat_slug, {})
        customer = customers.get(customer_id) if customer_id else None

        if not trigger or not merchant or not category:
            print(f"  WARNING: Missing context for {test_id} — skipping")
            continue

        try:
            composed = comp.compose(
                trigger=trigger,
                merchant=merchant,
                category=category,
                customer=customer,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            composed = {
                "body": f"Hi — relevant update for your {cat_slug} business. Want to know more?",
                "cta": "open_ended",
                "rationale": "Fallback due to composition error.",
            }

        is_customer_scope = trigger.get("scope") == "customer" or customer is not None
        send_as = "merchant_on_behalf" if is_customer_scope else "vera"

        line = {
            "test_id": test_id,
            "trigger_id": trigger_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "open_ended"),
            "send_as": send_as,
            "suppression_key": trigger.get("suppression_key", f"submission:{test_id}"),
            "rationale": composed.get("rationale", ""),
        }
        lines.append(line)
        print(f"  OK body: {composed.get('body', '')[:80]}...")

    # Step 4: Write
    with open(SUBMISSION_FILE, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(f"\nDone! Wrote {len(lines)} lines to {SUBMISSION_FILE}")


if __name__ == "__main__":
    main()
