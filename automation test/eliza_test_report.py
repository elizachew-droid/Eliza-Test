#!/usr/bin/env python3
"""
eliza_test_report.py
--------------------
Builds the "Eliza Test" report:
  - NORAM region accounts (US, CA, MX)
  - Sub-vertical contains 'gift card' (case-insensitive)
  - Columns: Account Name, Account Owner, Annual Revenue, PSP, Sub-Vertical

Run discovery mode first to confirm field API names:
    python eliza_test_report.py --discover

Then run the full report:
    python eliza_test_report.py
    python eliza_test_report.py --output-csv ./output/eliza_test.csv
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from sf_auth import get_salesforce_client

logging.basicConfig(format="%(levelname)-8s %(message)s", level=logging.INFO)

# ---------------------------------------------------------------------------
# Field discovery — searches Account object for the right API names
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS = {
    "sub_vertical": ["vertical", "subvertical", "sub_vertical", "sub-vertical", "industry_sub"],
    "psp":          ["psp", "payment_service", "payment_processor", "acquirer", "processor"],
    "region":       ["region", "noram", "geography", "geo"],
}

NORAM_COUNTRIES = ("US", "USA", "United States", "CA", "Canada", "MX", "Mexico")


def discover_fields(sf) -> dict[str, list[tuple[str, str]]]:
    """
    Describe the Account object and find fields whose API name or label
    matches the search keywords above.
    Returns {category: [(api_name, label), ...]}
    """
    logging.info("Describing Account object…")
    meta = sf.Account.describe()
    fields = meta["fields"]

    matches: dict[str, list[tuple[str, str]]] = {}
    for category, keywords in SEARCH_KEYWORDS.items():
        hits = []
        for f in fields:
            api  = f["name"].lower()
            label = f["label"].lower()
            if any(kw in api or kw in label for kw in keywords):
                hits.append((f["name"], f["label"]))
        matches[category] = hits

    return matches


def print_discovery(matches: dict[str, list[tuple[str, str]]]) -> None:
    print("\n" + "=" * 60)
    print("FIELD DISCOVERY — Account object")
    print("=" * 60)
    for category, hits in matches.items():
        print(f"\n  [{category.upper()}]")
        if hits:
            for api_name, label in hits:
                print(f"    {api_name:<45} ({label})")
        else:
            print("    (no matches found)")
    print()
    print("Set the correct API names in .env or pass --sub-vertical-field")
    print("and --psp-field flags, then re-run without --discover.\n")


# ---------------------------------------------------------------------------
# Report query
# ---------------------------------------------------------------------------

def build_soql(sub_vertical_field: str, psp_field: str, owner_field: str = "Owner.Name") -> str:
    countries = ", ".join(f"'{c}'" for c in NORAM_COUNTRIES)
    return (
        f"SELECT Name, {owner_field}, AnnualRevenue, "
        f"{sub_vertical_field}, {psp_field} "
        f"FROM Account "
        f"WHERE BillingCountry IN ({countries}) "
        f"AND {sub_vertical_field} LIKE '%gift card%' "
        f"ORDER BY AnnualRevenue DESC NULLS LAST"
    )


def run_report(sf, sub_vertical_field: str, psp_field: str) -> list[dict]:
    soql = build_soql(sub_vertical_field, psp_field)
    logging.info("Running query…")
    logging.debug("SOQL: %s", soql)

    try:
        result = sf.query_all(soql)
    except Exception as exc:
        logging.error("Query failed: %s", exc)
        logging.error(
            "Likely cause: one of the field API names is wrong.\n"
            "Run with --discover to find the correct names, then\n"
            "set SF_SUB_VERTICAL_FIELD and SF_PSP_FIELD in .env."
        )
        sys.exit(1)

    records = result.get("records", [])
    logging.info("Found %d account(s).", len(records))
    return records


def print_table(records: list[dict], sub_vertical_field: str, psp_field: str) -> None:
    if not records:
        print("\nNo NORAM accounts found with 'gift card' as sub-vertical.\n")
        return

    print("\n" + "=" * 100)
    print("ELIZA TEST — NORAM Gift Card Accounts")
    print("=" * 100)
    print(f"  {'Account Name':<40} {'Owner':<25} {'Revenue':>14}  {'PSP':<20}  Sub-Vertical")
    print("  " + "-" * 95)

    for r in records:
        owner = (r.get("Owner") or {}).get("Name", "—")
        revenue = r.get("AnnualRevenue")
        revenue_str = f"${revenue:,.0f}" if revenue else "—"
        psp = r.get(psp_field) or "—"
        sub_v = r.get(sub_vertical_field) or "—"
        print(f"  {r['Name']:<40} {owner:<25} {revenue_str:>14}  {psp:<20}  {sub_v}")

    print(f"\n  Total: {len(records)} account(s)\n")


def write_csv(records: list[dict], sub_vertical_field: str, psp_field: str, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Account Name", "Account Owner", "Annual Revenue", "PSP", "Sub-Vertical"])
        for r in records:
            owner = (r.get("Owner") or {}).get("Name", "")
            writer.writerow([
                r.get("Name", ""),
                owner,
                r.get("AnnualRevenue", ""),
                r.get(psp_field, ""),
                r.get(sub_vertical_field, ""),
            ])
    logging.info("Report saved to %s", path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Generate the "Eliza Test" NORAM gift card accounts report.'
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Show all Account fields matching 'vertical', 'psp', 'region' — use this first.",
    )
    parser.add_argument(
        "--sub-vertical-field",
        default=os.getenv("SF_SUB_VERTICAL_FIELD", "Sub_Vertical__c"),
        help="API name of the sub-vertical field (default: $SF_SUB_VERTICAL_FIELD or Sub_Vertical__c)",
    )
    parser.add_argument(
        "--psp-field",
        default=os.getenv("SF_PSP_FIELD", "PSP__c"),
        help="API name of the PSP field (default: $SF_PSP_FIELD or PSP__c)",
    )
    parser.add_argument(
        "--output-csv",
        metavar="PATH",
        default="./output/eliza_test.csv",
        help="Where to save the CSV (default: ./output/eliza_test.csv)",
    )
    args = parser.parse_args()

    sf = get_salesforce_client()

    if args.discover:
        matches = discover_fields(sf)
        print_discovery(matches)
        return

    records = run_report(sf, args.sub_vertical_field, args.psp_field)
    print_table(records, args.sub_vertical_field, args.psp_field)
    write_csv(records, args.sub_vertical_field, args.psp_field, args.output_csv)


if __name__ == "__main__":
    main()
