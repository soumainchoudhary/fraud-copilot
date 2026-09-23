"""Generate synthetic fraud case narratives from flagged transactions.

Produces realistic investigation case records by combining flagged transaction
data with Faker-generated identities and templated complaint/investigator text.

Usage:
    python -m app.data.synthetic_cases
"""
from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from faker import Faker

# Seed for reproducibility
fake = Faker(["en_US", "en_IN"])
Faker.seed(42)
random.seed(42)

# --- Output ---
OUTPUT_DIR = Path("data")
OUTPUT_PATH = OUTPUT_DIR / "synthetic_cases.json"

# --- Templates (10+ variations each for natural variety) ---

COMPLAINT_TEMPLATES = [
    "Customer {name} reported unauthorized transaction of ₹{amount:.2f} on {date}. Card ending {card_last4} was used at {merchant}.",
    "Alert triggered: high-risk transaction of ₹{amount:.2f} from account {account} via UPI ID {upi_id}. No prior transaction history with merchant {merchant}.",
    "Repeated low-value transactions totaling ₹{amount:.2f} flagged for potential structuring. Account holder {name} denies initiating transfers.",
    "Customer {name} contacted helpline reporting ₹{amount:.2f} debited without OTP verification. Transaction originated from IP {ip_address}.",
    "Suspicious cross-border transaction of ₹{amount:.2f} flagged. Account {account} registered in {city} but transaction geolocated to {foreign_city}.",
    "Multiple failed login attempts followed by successful ₹{amount:.2f} transfer from account {account}. Possible credential stuffing attack.",
    "Account {account} linked to UPI ID {upi_id} received rapid inbound transfers totaling ₹{amount:.2f} from {num_senders} unique senders within 2 hours.",
    "Customer {name} reports card cloning. Transaction of ₹{amount:.2f} at {merchant} while card was in customer's possession.",
    "Night-time transaction of ₹{amount:.2f} flagged for account {account}. Transaction at {time_str} falls outside customer's typical activity window.",
    "Velocity rule breach: {num_txns} transactions totaling ₹{amount:.2f} within 15 minutes on account {account}. UPI ID {upi_id}.",
    "Large withdrawal of ₹{amount:.2f} from ATM in {city} flagged. Account holder {name} last active in {home_city} 30 minutes prior.",
    "SIM swap suspected for mobile number linked to account {account}. Post-swap transaction of ₹{amount:.2f} to UPI {upi_id}.",
]

INVESTIGATOR_NOTE_TEMPLATES = [
    "Cross-referenced transaction with merchant database. Merchant {merchant} has {merchant_flag_count} prior fraud reports. Recommend escalation to L2.",
    "Device fingerprint analysis shows login from new device (Android, {city}). Previous logins exclusively from iOS, {home_city}. Account credentials likely compromised.",
    "UPI ID {upi_id} linked to {linked_count} accounts across 3 banks. Pattern consistent with mule account network. Flagged all linked accounts.",
    "CCTV footage requested from ATM location. Customer's KYC address verified — matches registered address in {home_city}. Awaiting video confirmation.",
    "Transaction reversal initiated. Customer provided FIR copy #{fir_number}. Case under Section 420 IPC. Provisional credit issued.",
    "Behavioral analytics confirm anomaly: average transaction value for this account is ₹{avg_amount:.2f}; flagged transaction is {multiplier:.1f}x the average.",
    "Network graph analysis: account {account} is 2 hops from known fraud ring (Ring ID: FR-{ring_id}). Monitoring all connected accounts.",
    "IP geolocation traces to VPN endpoint ({vpn_location}). Unable to determine true origin. Recommend blocking VPN-originated transactions for this account.",
    "Pattern matches 'triangulation fraud' typology: buyer → legitimate merchant → fraudster. Goods delivered to address not matching any account holder.",
    "Reviewed last 30 days of activity. {suspicious_count} transactions deviate from established spending pattern. Cumulative risk score elevated.",
]

STATUS_OPTIONS = ["open", "escalated", "under_review", "resolved", "closed"]
STATUS_WEIGHTS = [0.35, 0.25, 0.20, 0.15, 0.05]


def _generate_upi_id() -> str:
    """Generate a realistic Indian UPI ID."""
    providers = ["@okicici", "@oksbi", "@ybl", "@paytm", "@upi", "@axl", "@ibl"]
    username = fake.user_name()[:12]
    return f"{username}{random.choice(providers)}"


def _generate_account_number() -> str:
    """Generate a realistic bank account number."""
    return "".join([str(random.randint(0, 9)) for _ in range(12)])


def generate_case(
    transaction_id: str | None = None,
    risk_score: float | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Generate a single synthetic fraud case record.

    Args:
        transaction_id: Optional external transaction ID to link.
        risk_score: Optional risk score from the scoring model.
        amount: Optional transaction amount.

    Returns:
        Dict representing a complete case record.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    txn_id = transaction_id or f"TXN-{uuid.uuid4().hex[:10].upper()}"
    score = risk_score if risk_score is not None else round(random.uniform(0.55, 0.99), 4)
    txn_amount = amount if amount is not None else round(random.uniform(500, 250000), 2)

    # Generate identity
    name = fake.name()
    account = _generate_account_number()
    upi_id = _generate_upi_id()
    card_last4 = f"{random.randint(1000, 9999)}"
    home_city = fake.city()

    # Generate linked accounts (mule network simulation)
    num_linked = random.randint(0, 4)
    linked_accounts = [_generate_account_number() for _ in range(num_linked)]

    # Timestamp
    txn_date = fake.date_time_between(start_date="-30d", end_date="now")

    # Fill complaint template
    complaint_template = random.choice(COMPLAINT_TEMPLATES)
    complaint = complaint_template.format(
        name=name,
        amount=txn_amount,
        date=txn_date.strftime("%Y-%m-%d %H:%M"),
        card_last4=card_last4,
        merchant=fake.company(),
        account=account,
        upi_id=upi_id,
        ip_address=fake.ipv4_public(),
        city=home_city,
        foreign_city=fake.city(),
        num_senders=random.randint(3, 15),
        time_str=txn_date.strftime("%H:%M"),
        num_txns=random.randint(5, 20),
        home_city=fake.city(),
    )

    # Fill investigator notes template
    notes_template = random.choice(INVESTIGATOR_NOTE_TEMPLATES)
    investigator_notes = notes_template.format(
        merchant=fake.company(),
        merchant_flag_count=random.randint(2, 47),
        city=fake.city(),
        home_city=home_city,
        upi_id=upi_id,
        linked_count=random.randint(3, 12),
        fir_number=random.randint(100000, 999999),
        avg_amount=round(random.uniform(200, 5000), 2),
        multiplier=round(txn_amount / max(random.uniform(200, 5000), 1), 1),
        account=account,
        ring_id=f"{random.randint(1000, 9999)}",
        vpn_location=random.choice(["Netherlands", "Romania", "Singapore", "Ukraine", "Brazil"]),
        suspicious_count=random.randint(3, 18),
    )

    status = random.choices(STATUS_OPTIONS, weights=STATUS_WEIGHTS, k=1)[0]

    return {
        "case_id": case_id,
        "transaction_id": txn_id,
        "account_holder": name,
        "account_number": account,
        "upi_id": upi_id,
        "card_last4": card_last4,
        "phone": fake.phone_number(),
        "email": fake.email(),
        "address": f"{fake.street_address()}, {home_city}",
        "risk_score": score,
        "amount": txn_amount,
        "timestamp": txn_date.isoformat(),
        "complaint_text": complaint,
        "investigator_notes": investigator_notes,
        "status": status,
        "linked_accounts": linked_accounts,
        "assigned_to": f"INV-{random.randint(100, 999)}",
        "created_at": (txn_date + timedelta(hours=random.randint(1, 48))).isoformat(),
    }


def generate_cases(n: int = 200) -> list[dict[str, Any]]:
    """Generate n synthetic case records."""
    return [generate_case() for _ in range(n)]


def save_cases(cases: list[dict[str, Any]], path: Path | None = None) -> Path:
    """Save cases to a JSON file."""
    output = path or OUTPUT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False, default=str)
    print(f"Generated {len(cases)} synthetic case records → {output}")
    return output


if __name__ == "__main__":
    cases = generate_cases(200)
    save_cases(cases)

    # Print sample
    print("\nSample case record:")
    print(json.dumps(cases[0], indent=2, default=str))
