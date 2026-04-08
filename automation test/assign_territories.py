#!/usr/bin/env python3
"""
assign_territories.py
---------------------
Reads territory / pod assignment rules from pod_manifest_template.json and
applies them to Salesforce Account records.

Rules are evaluated in priority order.  The first matching rule wins.
Accounts are matched by: BillingCountry, BillingState, Industry, AnnualRevenue
range, NumberOfEmployees range, and/or Account Type.

Usage:
    # Validate without writing anything:
    python assign_territories.py --dry-run

    # Apply assignments to Salesforce (only after reviewing dry-run output):
    python assign_territories.py

    # Limit to a specific segment:
    python assign_territories.py --segment Enterprise --dry-run

    # Write a CSV report:
    python assign_territories.py --dry-run --output-csv ./output/territory_assignments.csv
"""

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TerritoryRule:
    priority: int
    territory: str
    pod: str
    segment: str
    region: str
    account_tier: str
    conditions: dict[str, Any]  # raw conditions dict from manifest


@dataclass
class AssignmentResult:
    account_id: str
    account_name: str
    matched_rule_priority: int | None
    old_territory: str | None
    new_territory: str | None
    old_pod: str | None
    new_pod: str | None
    old_segment: str | None
    new_segment: str | None
    changed: bool = False
    skipped_reason: str = ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(format="%(levelname)-8s %(message)s", level=level)


# ---------------------------------------------------------------------------
# Salesforce helpers
# ---------------------------------------------------------------------------

def get_salesforce_client():
    try:
        from simple_salesforce import Salesforce, SalesforceAuthenticationFailed
    except ImportError:
        logging.error("simple_salesforce not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    username = os.getenv("SF_USERNAME", "")
    password = os.getenv("SF_PASSWORD", "")
    security_token = os.getenv("SF_SECURITY_TOKEN", "")
    instance_url = os.getenv("SF_INSTANCE_URL", "")
    client_id = os.getenv("SF_CLIENT_ID", "")
    client_secret = os.getenv("SF_CLIENT_SECRET", "")
    api_version = os.getenv("SF_API_VERSION", "59.0")

    for name, val in {"SF_USERNAME": username, "SF_PASSWORD": password, "SF_INSTANCE_URL": instance_url}.items():
        if not val:
            logging.error("Missing required env var: %s", name)
            sys.exit(1)

    domain = "test" if "test.salesforce" in instance_url.lower() else "login"

    try:
        return Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            consumer_key=client_id or None,
            consumer_secret=client_secret or None,
            domain=domain,
            version=api_version,
        )
    except SalesforceAuthenticationFailed as exc:
        logging.error("Salesforce auth failed: %s", exc)
        sys.exit(1)


def fetch_accounts(sf, segment_filter: str | None) -> list[dict]:
    territory_field = os.getenv("SF_TERRITORY_FIELD", "Territory__c")
    pod_field = os.getenv("SF_POD_FIELD", "Pod__c")
    segment_field = os.getenv("SF_SEGMENT_FIELD", "Segment__c")
    region_field = os.getenv("SF_REGION_FIELD", "Region__c")
    tier_field = os.getenv("SF_ACCOUNT_TIER_FIELD", "Account_Tier__c")

    where_clause = ""
    if segment_filter:
        where_clause = f"WHERE {segment_field} = '{segment_filter}'"

    soql = (
        f"SELECT Id, Name, Industry, AnnualRevenue, NumberOfEmployees, "
        f"BillingCountry, BillingState, Type, "
        f"{territory_field}, {pod_field}, {segment_field}, {region_field}, {tier_field} "
        f"FROM Account {where_clause} "
        f"ORDER BY Name"
    )

    logging.info("Querying Salesforce accounts…")
    result = sf.query_all(soql)
    records = result.get("records", [])
    logging.info("Fetched %d account(s).", len(records))
    return records


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def load_rules(manifest_path: str) -> list[TerritoryRule]:
    path = Path(manifest_path)
    if not path.exists():
        logging.error("Pod manifest not found: %s", manifest_path)
        sys.exit(1)

    with open(path) as fh:
        manifest = json.load(fh)

    rules = []
    for entry in manifest.get("territory_rules", []):
        rules.append(
            TerritoryRule(
                priority=entry.get("priority", 999),
                territory=entry.get("territory", ""),
                pod=entry.get("pod", ""),
                segment=entry.get("segment", ""),
                region=entry.get("region", ""),
                account_tier=entry.get("account_tier", ""),
                conditions=entry.get("conditions", {}),
            )
        )

    rules.sort(key=lambda r: r.priority)
    logging.info("Loaded %d territory rule(s) from %s.", len(rules), manifest_path)
    return rules


def _matches(account: dict, conditions: dict[str, Any]) -> bool:
    """Return True if the account satisfies all conditions in the rule."""
    for key, value in conditions.items():
        acct_val = account.get(key)

        if key == "BillingCountry":
            countries = [value] if isinstance(value, str) else value
            if acct_val not in countries:
                return False

        elif key == "BillingState":
            states = [value] if isinstance(value, str) else value
            if acct_val not in states:
                return False

        elif key == "Industry":
            industries = [value] if isinstance(value, str) else value
            if acct_val not in industries:
                return False

        elif key == "Type":
            types = [value] if isinstance(value, str) else value
            if acct_val not in types:
                return False

        elif key == "AnnualRevenue":
            revenue = acct_val or 0
            min_rev = value.get("min", 0)
            max_rev = value.get("max", float("inf"))
            if not (min_rev <= revenue <= max_rev):
                return False

        elif key == "NumberOfEmployees":
            employees = acct_val or 0
            min_emp = value.get("min", 0)
            max_emp = value.get("max", float("inf"))
            if not (min_emp <= employees <= max_emp):
                return False

    return True


def evaluate_rules(account: dict, rules: list[TerritoryRule]) -> TerritoryRule | None:
    for rule in rules:
        if _matches(account, rule.conditions):
            return rule
    return None


# ---------------------------------------------------------------------------
# Assignment logic
# ---------------------------------------------------------------------------

def compute_assignments(
    accounts: list[dict],
    rules: list[TerritoryRule],
) -> list[AssignmentResult]:
    territory_field = os.getenv("SF_TERRITORY_FIELD", "Territory__c")
    pod_field = os.getenv("SF_POD_FIELD", "Pod__c")
    segment_field = os.getenv("SF_SEGMENT_FIELD", "Segment__c")

    results = []
    for acct in accounts:
        rule = evaluate_rules(acct, rules)
        old_territory = acct.get(territory_field)
        old_pod = acct.get(pod_field)
        old_segment = acct.get(segment_field)

        if rule is None:
            results.append(
                AssignmentResult(
                    account_id=acct["Id"],
                    account_name=acct["Name"],
                    matched_rule_priority=None,
                    old_territory=old_territory,
                    new_territory=None,
                    old_pod=old_pod,
                    new_pod=None,
                    old_segment=old_segment,
                    new_segment=None,
                    changed=False,
                    skipped_reason="No matching rule",
                )
            )
            continue

        new_territory = rule.territory or old_territory
        new_pod = rule.pod or old_pod
        new_segment = rule.segment or old_segment
        changed = (
            new_territory != old_territory
            or new_pod != old_pod
            or new_segment != old_segment
        )

        results.append(
            AssignmentResult(
                account_id=acct["Id"],
                account_name=acct["Name"],
                matched_rule_priority=rule.priority,
                old_territory=old_territory,
                new_territory=new_territory,
                old_pod=old_pod,
                new_pod=new_pod,
                old_segment=old_segment,
                new_segment=new_segment,
                changed=changed,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_dry_run_summary(results: list[AssignmentResult]) -> None:
    changes = [r for r in results if r.changed]
    no_match = [r for r in results if not r.matched_rule_priority]
    unchanged = [r for r in results if r.matched_rule_priority and not r.changed]

    print("\n" + "=" * 70)
    print("DRY-RUN SUMMARY — assign_territories.py")
    print("=" * 70)
    print(f"  Total accounts evaluated : {len(results)}")
    print(f"  Would be updated         : {len(changes)}")
    print(f"  Already correct          : {len(unchanged)}")
    print(f"  No rule matched          : {len(no_match)}")
    print()

    if changes:
        print("ACCOUNTS THAT WOULD CHANGE:")
        print(f"  {'Account Name':<40} {'Territory':>12} {'Pod':>12} {'Segment':>12}")
        print("  " + "-" * 76)
        for r in changes:
            territory_change = f"{r.old_territory or '—'} → {r.new_territory or '—'}"
            pod_change = f"{r.old_pod or '—'} → {r.new_pod or '—'}"
            segment_change = f"{r.old_segment or '—'} → {r.new_segment or '—'}"
            print(f"  {r.account_name:<40} {territory_change:>20} {pod_change:>20} {segment_change:>20}")
        print()

    if no_match:
        print("ACCOUNTS WITH NO MATCHING RULE (will not be touched):")
        for r in no_match:
            print(f"  - {r.account_name} ({r.account_id})")
        print()

    print("[DRY-RUN] No writes were made to Salesforce.")
    print("          Review the output above, then re-run without --dry-run to apply.\n")


def write_csv(results: list[AssignmentResult], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "account_id", "account_name", "matched_rule_priority",
            "old_territory", "new_territory",
            "old_pod", "new_pod",
            "old_segment", "new_segment",
            "changed", "skipped_reason",
        ])
        for r in results:
            writer.writerow([
                r.account_id, r.account_name, r.matched_rule_priority,
                r.old_territory, r.new_territory,
                r.old_pod, r.new_pod,
                r.old_segment, r.new_segment,
                r.changed, r.skipped_reason,
            ])
    logging.info("CSV written to %s", output_path)


# ---------------------------------------------------------------------------
# Salesforce write
# ---------------------------------------------------------------------------

def apply_assignments(sf, results: list[AssignmentResult]) -> None:
    territory_field = os.getenv("SF_TERRITORY_FIELD", "Territory__c")
    pod_field = os.getenv("SF_POD_FIELD", "Pod__c")
    segment_field = os.getenv("SF_SEGMENT_FIELD", "Segment__c")
    batch_size = int(os.getenv("BATCH_SIZE", "200"))

    changes = [r for r in results if r.changed]
    if not changes:
        logging.info("No accounts require updates.")
        return

    logging.info("Applying %d assignment(s) to Salesforce…", len(changes))

    records_to_update = [
        {
            "Id": r.account_id,
            territory_field: r.new_territory,
            pod_field: r.new_pod,
            segment_field: r.new_segment,
        }
        for r in changes
    ]

    success, fail = 0, 0
    for i in range(0, len(records_to_update), batch_size):
        batch = records_to_update[i : i + batch_size]
        try:
            sf.bulk.Account.update(batch)
            success += len(batch)
            logging.info("  Batch %d–%d: OK", i + 1, i + len(batch))
        except Exception as exc:
            fail += len(batch)
            logging.error("  Batch %d–%d failed: %s", i + 1, i + len(batch), exc)

    print(f"\nApplied: {success} record(s) updated, {fail} failed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign territories and pods to Salesforce accounts using manifest rules."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to Salesforce.",
    )
    parser.add_argument(
        "--segment",
        metavar="SEGMENT_NAME",
        help="Only process accounts whose Segment field matches this value.",
    )
    parser.add_argument(
        "--output-csv",
        metavar="PATH",
        help="Write a CSV report of all assignment decisions to this path.",
    )
    parser.add_argument(
        "--manifest",
        default=os.getenv("POD_MANIFEST_PATH", "./pod_manifest_template.json"),
        metavar="PATH",
        help="Path to the pod manifest JSON (default: $POD_MANIFEST_PATH).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    if args.dry_run:
        logging.info("DRY-RUN mode — no writes will be made to Salesforce.")

    sf = get_salesforce_client()
    accounts = fetch_accounts(sf, args.segment)
    rules = load_rules(args.manifest)
    results = compute_assignments(accounts, rules)

    if args.output_csv:
        write_csv(results, args.output_csv)

    if args.dry_run:
        print_dry_run_summary(results)
    else:
        apply_assignments(sf, results)
        logging.info("Done.")


if __name__ == "__main__":
    main()
