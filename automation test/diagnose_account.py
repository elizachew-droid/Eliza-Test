#!/usr/bin/env python3
"""Quick diagnostic: inspect one account and show all revenue-related fields."""
import os, sys
from dotenv import load_dotenv
load_dotenv()
from sf_auth import get_salesforce_client

ACCOUNT_ID = "0010800002mXdVxAAK"

sf = get_salesforce_client()

# 1. Describe Account — find every field with 'revenue', 'arr', 'mrr', 'value' in name/label
meta   = sf.Account.describe()
rev_fields = [
    f["name"] for f in meta["fields"]
    if any(kw in f["name"].lower() or kw in f["label"].lower()
           for kw in ["revenue","arr","mrr","value","tpv","volume"])
]
print("\nRevenue-related fields on Account object:")
for f in sorted(rev_fields):
    print(f"  {f}")

# 2. Query that specific account for those fields + standard ones
fields_to_fetch = ["Id","Name","AnnualRevenue","Owner.Name","BillingState","BillingCountry"] + rev_fields
# Deduplicate preserving order
seen = set(); unique_fields = []
for f in fields_to_fetch:
    if f not in seen:
        seen.add(f); unique_fields.append(f)

soql = f"SELECT {', '.join(unique_fields)} FROM Account WHERE Id = '{ACCOUNT_ID}'"
try:
    result = sf.query(soql)
    records = result.get("records", [])
    if not records:
        print(f"\nNo account found with Id {ACCOUNT_ID}")
        sys.exit(1)
    r = records[0]
    print(f"\nAccount: {r.get('Name')} ({ACCOUNT_ID})")
    print("-" * 50)
    for field in unique_fields:
        val = r.get(field)
        if val not in (None, "", {}) and field != "attributes":
            print(f"  {field:<45} = {val}")
except Exception as exc:
    print(f"Query error: {exc}")
