#!/usr/bin/env python3
"""
meddic_audit.py
---------------
Audits open Salesforce Opportunities for MEDDIC completeness.

For each opportunity in the configured pipeline stages it checks whether each
of the six MEDDIC dimensions has been filled in.  Opportunities below the
minimum score threshold are flagged as at-risk.

Optionally updates the MEDDIC_Score__c field on each opportunity with the
computed score (requires --apply to write; --dry-run is the safe default).

Usage:
    # Validate / report without writing anything:
    python meddic_audit.py --dry-run

    # Write MEDDIC scores back to Salesforce:
    python meddic_audit.py --apply

    # Filter to a specific owner:
    python meddic_audit.py --dry-run --owner-id 005Xxxxxxxxxxxxxxx

    # Export to CSV:
    python meddic_audit.py --dry-run --output-csv ./output/meddic_audit.csv
"""

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sf_auth import get_salesforce_client  # noqa: E402


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

MEDDIC_DIMENSIONS = [
    "metrics",
    "economic_buyer",
    "decision_criteria",
    "decision_process",
    "identify_pain",
    "champion",
]


@dataclass
class OpportunityAudit:
    opp_id: str
    opp_name: str
    account_name: str
    stage: str
    amount: float | None
    close_date: str
    owner_name: str
    # MEDDIC values — None means the field is blank/empty
    metrics: str | None
    economic_buyer: str | None
    decision_criteria: str | None
    decision_process: str | None
    identify_pain: str | None
    champion: str | None
    # Computed
    score: int = 0
    at_risk: bool = False
    existing_score: float | None = None

    def compute_score(self) -> int:
        self.score = sum(
            1
            for dim in MEDDIC_DIMENSIONS
            if getattr(self, dim) not in (None, "", "null")
        )
        min_score = int(os.getenv("MEDDIC_MIN_SCORE", "3"))
        self.at_risk = self.score < min_score
        return self.score

    def missing_dimensions(self) -> list[str]:
        return [
            dim
            for dim in MEDDIC_DIMENSIONS
            if getattr(self, dim) in (None, "", "null")
        ]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(format="%(levelname)-8s %(message)s", level=level)


# ---------------------------------------------------------------------------
# Salesforce helpers
# ---------------------------------------------------------------------------

# get_salesforce_client is imported from sf_auth


def fetch_opportunities(sf, owner_id: str | None) -> list[dict]:
    metrics_field = os.getenv("SF_MEDDIC_METRICS_FIELD", "Metrics__c")
    econ_buyer_field = os.getenv("SF_MEDDIC_ECONOMIC_BUYER_FIELD", "Economic_Buyer__c")
    dec_criteria_field = os.getenv("SF_MEDDIC_DECISION_CRITERIA_FIELD", "Decision_Criteria__c")
    dec_process_field = os.getenv("SF_MEDDIC_DECISION_PROCESS_FIELD", "Decision_Process__c")
    pain_field = os.getenv("SF_MEDDIC_IDENTIFY_PAIN_FIELD", "Identify_Pain__c")
    champion_field = os.getenv("SF_MEDDIC_CHAMPION_FIELD", "Champion__c")
    score_field = os.getenv("SF_MEDDIC_SCORE_FIELD", "MEDDIC_Score__c")

    target_stages = os.getenv(
        "MEDDIC_TARGET_STAGES",
        "Qualification,Discovery,Proposal,Negotiation,Closing",
    )
    stage_list = ", ".join(f"'{s.strip()}'" for s in target_stages.split(","))

    where_parts = [f"StageName IN ({stage_list})", "IsClosed = false"]
    if owner_id:
        where_parts.append(f"OwnerId = '{owner_id}'")

    where_clause = " AND ".join(where_parts)

    soql = (
        f"SELECT Id, Name, Account.Name, StageName, Amount, CloseDate, "
        f"Owner.Name, "
        f"{metrics_field}, {econ_buyer_field}, {dec_criteria_field}, "
        f"{dec_process_field}, {pain_field}, {champion_field}, {score_field} "
        f"FROM Opportunity "
        f"WHERE {where_clause} "
        f"ORDER BY Amount DESC NULLS LAST"
    )

    logging.info("Querying Salesforce opportunities…")
    result = sf.query_all(soql)
    records = result.get("records", [])
    logging.info("Fetched %d opportunity(-ies).", len(records))
    return records


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------

def build_audits(records: list[dict]) -> list[OpportunityAudit]:
    metrics_field = os.getenv("SF_MEDDIC_METRICS_FIELD", "Metrics__c")
    econ_buyer_field = os.getenv("SF_MEDDIC_ECONOMIC_BUYER_FIELD", "Economic_Buyer__c")
    dec_criteria_field = os.getenv("SF_MEDDIC_DECISION_CRITERIA_FIELD", "Decision_Criteria__c")
    dec_process_field = os.getenv("SF_MEDDIC_DECISION_PROCESS_FIELD", "Decision_Process__c")
    pain_field = os.getenv("SF_MEDDIC_IDENTIFY_PAIN_FIELD", "Identify_Pain__c")
    champion_field = os.getenv("SF_MEDDIC_CHAMPION_FIELD", "Champion__c")
    score_field = os.getenv("SF_MEDDIC_SCORE_FIELD", "MEDDIC_Score__c")

    audits = []
    for r in records:
        account_name = (r.get("Account") or {}).get("Name", "Unknown Account")
        owner_name = (r.get("Owner") or {}).get("Name", "Unknown Owner")

        audit = OpportunityAudit(
            opp_id=r["Id"],
            opp_name=r["Name"],
            account_name=account_name,
            stage=r.get("StageName", ""),
            amount=r.get("Amount"),
            close_date=str(r.get("CloseDate", "")),
            owner_name=owner_name,
            metrics=r.get(metrics_field),
            economic_buyer=r.get(econ_buyer_field),
            decision_criteria=r.get(dec_criteria_field),
            decision_process=r.get(dec_process_field),
            identify_pain=r.get(pain_field),
            champion=r.get(champion_field),
            existing_score=r.get(score_field),
        )
        audit.compute_score()
        audits.append(audit)

    return audits


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_dry_run_summary(audits: list[OpportunityAudit]) -> None:
    at_risk = [a for a in audits if a.at_risk]
    healthy = [a for a in audits if not a.at_risk]
    score_field = os.getenv("SF_MEDDIC_SCORE_FIELD", "MEDDIC_Score__c")
    min_score = int(os.getenv("MEDDIC_MIN_SCORE", "3"))

    print("\n" + "=" * 70)
    print("DRY-RUN SUMMARY — meddic_audit.py")
    print("=" * 70)
    print(f"  Total opportunities audited : {len(audits)}")
    print(f"  At-risk (score < {min_score})        : {len(at_risk)}")
    print(f"  Healthy (score >= {min_score})        : {len(healthy)}")
    print()

    if at_risk:
        total_at_risk_arr = sum((a.amount or 0) for a in at_risk)
        print(f"AT-RISK OPPORTUNITIES  (${total_at_risk_arr:,.0f} total ARR at risk)")
        print(
            f"  {'Opportunity':<35} {'Account':<25} {'Stage':<15} "
            f"{'Score':>5}  Missing MEDDIC Dimensions"
        )
        print("  " + "-" * 110)
        for a in sorted(at_risk, key=lambda x: x.score):
            missing = ", ".join(a.missing_dimensions()) or "—"
            amount_str = f"${a.amount:,.0f}" if a.amount else "—"
            print(
                f"  {a.opp_name:<35} {a.account_name:<25} {a.stage:<15} "
                f"{a.score:>3}/6  {missing}  [{amount_str}]"
            )
        print()

    score_updates = [a for a in audits if a.existing_score != a.score]
    if score_updates:
        print(
            f"SCORE FIELD UPDATES ({len(score_updates)} records would be written "
            f"to {score_field}):"
        )
        for a in score_updates[:20]:
            print(
                f"  {a.opp_name:<40} {a.existing_score or '—'} → {a.score}"
            )
        if len(score_updates) > 20:
            print(f"  … and {len(score_updates) - 20} more.")
        print()

    print("[DRY-RUN] No writes were made to Salesforce.")
    print("          Review the above, then re-run with --apply to write scores.\n")


def write_csv(audits: list[OpportunityAudit], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "opp_id", "opp_name", "account_name", "stage", "amount",
            "close_date", "owner_name",
            "metrics", "economic_buyer", "decision_criteria",
            "decision_process", "identify_pain", "champion",
            "score", "at_risk", "missing_dimensions", "existing_score",
        ])
        for a in audits:
            writer.writerow([
                a.opp_id, a.opp_name, a.account_name, a.stage,
                a.amount, a.close_date, a.owner_name,
                a.metrics, a.economic_buyer, a.decision_criteria,
                a.decision_process, a.identify_pain, a.champion,
                a.score, a.at_risk,
                "|".join(a.missing_dimensions()),
                a.existing_score,
            ])
    logging.info("CSV written to %s", output_path)


# ---------------------------------------------------------------------------
# Salesforce write
# ---------------------------------------------------------------------------

def apply_scores(sf, audits: list[OpportunityAudit]) -> None:
    score_field = os.getenv("SF_MEDDIC_SCORE_FIELD", "MEDDIC_Score__c")
    batch_size = int(os.getenv("BATCH_SIZE", "200"))

    to_update = [a for a in audits if a.existing_score != a.score]
    if not to_update:
        logging.info("All MEDDIC scores are already current — nothing to write.")
        return

    logging.info("Writing %d MEDDIC score update(s) to Salesforce…", len(to_update))

    records = [{"Id": a.opp_id, score_field: a.score} for a in to_update]
    success, fail = 0, 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        try:
            sf.bulk.Opportunity.update(batch)
            success += len(batch)
            logging.info("  Batch %d–%d: OK", i + 1, i + len(batch))
        except Exception as exc:
            fail += len(batch)
            logging.error("  Batch %d–%d failed: %s", i + 1, i + len(batch), exc)

    print(f"\nApplied: {success} score(s) written, {fail} failed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Salesforce Opportunities for MEDDIC completeness."
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(Default) Print audit results without writing to Salesforce.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write computed MEDDIC scores back to Salesforce Opportunities.",
    )

    parser.add_argument(
        "--owner-id",
        metavar="SF_USER_ID",
        help="Restrict audit to opportunities owned by this Salesforce User ID.",
    )
    parser.add_argument(
        "--output-csv",
        metavar="PATH",
        help="Write full audit results to this CSV path.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # --apply explicitly opts in to writes; anything else is dry-run
    dry_run = not args.apply
    setup_logging(args.log_level)

    if dry_run:
        logging.info("DRY-RUN mode — no writes will be made to Salesforce.")

    sf = get_salesforce_client()
    records = fetch_opportunities(sf, args.owner_id)
    audits = build_audits(records)

    if args.output_csv:
        write_csv(audits, args.output_csv)

    if dry_run:
        print_dry_run_summary(audits)
    else:
        apply_scores(sf, audits)
        logging.info("Done.")


if __name__ == "__main__":
    main()
