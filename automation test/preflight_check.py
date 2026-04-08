#!/usr/bin/env python3
"""
preflight_check.py
------------------
Connects to your Salesforce org and validates that every custom and standard
field API name referenced in the RevOps automation scripts actually exists on
the expected object.  Run this before assign_territories.py or meddic_audit.py.

Usage:
    python preflight_check.py
    python preflight_check.py --verbose
"""

import os
import sys
import argparse
import logging
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

from sf_auth import get_salesforce_client  # noqa: E402 (after load_dotenv)

# ---------------------------------------------------------------------------
# Field manifest — every API name the scripts touch, grouped by SObject.
# Update this dict whenever you add or remove a field reference in any script.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS: dict[str, list[str]] = {
    "Account": [
        # Standard fields
        "Id",
        "Name",
        "Industry",
        "AnnualRevenue",
        "NumberOfEmployees",
        "BillingCountry",
        "BillingState",
        "BillingCity",
        "OwnerId",
        "Type",
        "Rating",
        "Website",
        # Custom RevOps fields
        os.getenv("SF_TERRITORY_FIELD", "Territory__c"),
        os.getenv("SF_POD_FIELD", "Pod__c"),
        os.getenv("SF_SEGMENT_FIELD", "Segment__c"),
        os.getenv("SF_REGION_FIELD", "Region__c"),
        os.getenv("SF_ACCOUNT_TIER_FIELD", "Account_Tier__c"),
    ],
    "Opportunity": [
        # Standard fields
        "Id",
        "Name",
        "StageName",
        "Amount",
        "CloseDate",
        "AccountId",
        "OwnerId",
        "LeadSource",
        "Type",
        "Probability",
        "ForecastCategory",
        "NextStep",
        # Custom MEDDIC fields
        os.getenv("SF_MEDDIC_METRICS_FIELD", "Metrics__c"),
        os.getenv("SF_MEDDIC_ECONOMIC_BUYER_FIELD", "Economic_Buyer__c"),
        os.getenv("SF_MEDDIC_DECISION_CRITERIA_FIELD", "Decision_Criteria__c"),
        os.getenv("SF_MEDDIC_DECISION_PROCESS_FIELD", "Decision_Process__c"),
        os.getenv("SF_MEDDIC_IDENTIFY_PAIN_FIELD", "Identify_Pain__c"),
        os.getenv("SF_MEDDIC_CHAMPION_FIELD", "Champion__c"),
        os.getenv("SF_MEDDIC_SCORE_FIELD", "MEDDIC_Score__c"),
    ],
    "User": [
        "Id",
        "Name",
        "Email",
        "IsActive",
        "UserRoleId",
    ],
}


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(levelname)-8s %(message)s",
        level=level,
    )


# get_salesforce_client is imported from sf_auth


def get_object_fields(sf, sobject_name: str) -> set[str]:
    """Return the set of all field API names for a given SObject."""
    try:
        meta = getattr(sf, sobject_name).describe()
        return {f["name"] for f in meta["fields"]}
    except Exception as exc:
        logging.error("Could not describe %s: %s", sobject_name, exc)
        return set()


def run_preflight(sf, verbose: bool) -> dict[str, list[str]]:
    """
    Check all required fields against the org.
    Returns a dict of {sobject: [missing_field, ...]} for every missing field.
    """
    missing: dict[str, list[str]] = defaultdict(list)
    all_passed = True

    for sobject, fields in REQUIRED_FIELDS.items():
        logging.info("Checking %s (%d fields)…", sobject, len(fields))
        existing = get_object_fields(sf, sobject)

        if not existing:
            logging.warning("  Could not retrieve fields for %s — skipping.", sobject)
            continue

        for field in fields:
            if field in existing:
                logging.debug("  [OK]  %s.%s", sobject, field)
            else:
                logging.warning("  [MISSING]  %s.%s", sobject, field)
                missing[sobject].append(field)
                all_passed = False

    return dict(missing)


def print_report(missing: dict[str, list[str]]) -> None:
    print("\n" + "=" * 60)
    print("PREFLIGHT CHECK REPORT")
    print("=" * 60)

    if not missing:
        print("\n[PASS] All required fields exist in your Salesforce org.")
        print("       You are clear to run assign_territories.py and meddic_audit.py.\n")
        return

    print(
        f"\n[FAIL] {sum(len(v) for v in missing.values())} missing field(s) detected.\n"
    )
    for sobject, fields in sorted(missing.items()):
        print(f"  Object: {sobject}")
        for f in sorted(fields):
            print(f"    - {f}")
        print()

    print("Remediation options:")
    print("  1. Create the missing custom fields in Salesforce Setup.")
    print("  2. Update the corresponding SF_*_FIELD variable(s) in .env")
    print("     to match your org's actual API names.")
    print("  3. Re-run preflight_check.py to confirm all fields are present.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Salesforce field API names before running RevOps scripts."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show per-field OK/MISSING status."
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    sf = get_salesforce_client()
    missing = run_preflight(sf, args.verbose)
    print_report(missing)

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
