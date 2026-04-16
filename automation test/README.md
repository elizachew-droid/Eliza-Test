# Checkout.com NORAM RevOps Automation
## Claude Code Execution Guide

**Purpose:** Three-pillar automation for territory planning, OKR dashboarding, and forecast hygiene.
**Target:** $100BN TPV run rate | H2 2025
**Last updated:** 2025

---

## ⚠ Read Before Running Anything

This repo contains scripts that **write directly to your Salesforce production org**.
Two safeguards are built in:

1. `preflight_check.py` — validates permissions and field existence before any writes
2. `--dry-run` flag on all write scripts — prints what *would* happen without touching SF

**Rule: Never skip preflight. Never skip dry-run on first execution.**

---

## Repository Structure

```
/
├── README.md                        ← You are here
├── .env.example                     ← Copy to .env and populate
├── pod_manifest.json                ← YOU must populate this (see Step 2)
├── top_500.csv                      ← Your SF CSV export goes here
│
├── preflight_check.py               ← ALWAYS run first
├── assign_territories.py            ← Pillar I: Territory assignment
├── meddic_audit.py                  ← Pillar III: MEDDIC scoring
├── clari_pipeline_hygiene.py        ← Pillar III: Pipeline clean-up
│
├── lookml/
│   ├── opportunity.view.lkml        ← Pillar II: Core deal metrics
│   ├── opportunity_contact_role.view.lkml  ← SE/BDR attribution
│   ├── okr_targets.view.lkml        ← OKR target definitions
│   └── regional_performance.explore.lkml  ← Master explore
│
└── outputs/                         ← Auto-generated CSV reports land here
    ├── unassigned_accounts.csv
    ├── archive_candidates.csv
    ├── requalify_candidates.csv
    └── h2_high_velocity.csv
```

---

## Prerequisites

### Python Dependencies
```bash
pip install simple-salesforce pandas requests python-dotenv
```

### Environment Variables
Copy `.env.example` to `.env` and populate all values:
```bash
cp .env.example .env
```

```bash
# .env.example — copy to .env and fill in all values

# Salesforce credentials
SF_USERNAME=                  # e.g. john.doe@checkout.com
SF_PASSWORD=                  # Your SF password
SF_SECURITY_TOKEN=            # Setup > My Personal Information > Reset Security Token
SF_DOMAIN=login               # Use 'test' for sandbox, 'login' for production

# Apollo.io
APOLLO_API_KEY=               # Apollo dashboard > Settings > API Keys

# Environment flag (prevents accidental prod writes)
ENVIRONMENT=sandbox           # Change to 'production' only when ready for live run
```

> **How to find your SF Security Token:**
> Salesforce > Avatar (top right) > Settings > My Personal Information > Reset My Security Token
> It will be emailed to your SF login address.

---

## Execution Sequence

Follow this order exactly. Each step is a dependency for the next.

---

### STEP 0 — Preflight Check
**What it does:** Validates SF auth, checks all required custom fields exist, confirms Apollo key is present.
**Time:** ~30 seconds
**Writes to SF:** ❌ No

```bash
python preflight_check.py
```

**Expected output:**
```
✅ Salesforce authentication: PASSED
✅ Read Account object
✅ Read Opportunity object
✅ Read/Write custom field Account.Pod_Name__c
✅ Read/Write custom field Account.IC_Owner_Pod__c
✅ Read/Write Opportunity.MEDDIC_Audit_Score__c
✅ Apollo API key present

✅ All checks passed. Safe to proceed with write scripts.
```

**If fields are missing:** Create them in Salesforce before proceeding.
Go to: Setup > Object Manager > [Account or Opportunity] > Fields & Relationships > New

| Field Label | API Name | Type | Object |
|---|---|---|---|
| Pod Name | `Pod_Name__c` | Text(100) | Account |
| IC Owner Pod | `IC_Owner_Pod__c` | Text(100) | Account |
| Deal Segment | `Deal_Segment__c` | Picklist: Hype Deal / Long-term Strategic | Account |
| MEDDIC Audit Score | `MEDDIC_Audit_Score__c` | Number(3,0) | Opportunity |
| MEDDIC Audit Flag | `MEDDIC_Audit_Flag__c` | Checkbox | Opportunity |
| MEDDIC Missing Fields | `MEDDIC_Missing_Fields__c` | Text Area(255) | Opportunity |
| Expected TPV | `Expected_TPV__c` | Currency | Opportunity |

---

### STEP 1 — Prepare Your Input Files

**1a. Export top_500.csv from Salesforce**

Required columns (exact names):
```
AccountId, Account_Name, Annual_Revenue, Employee_Count, Industry, Deal_Segment
```
- `AccountId`: Salesforce 18-character Account ID (starts with `001`)
- `Deal_Segment`: Optional. If populated, overrides all automation logic. Use: `Hype Deal` or `Long-term Strategic`
- Leave `Annual_Revenue`, `Employee_Count`, `Industry` blank where unknown — Apollo will fill them

**1b. Populate pod_manifest.json**

This is the **only file that requires manual input from you.** It cannot be automated.

```json
{
  "pods": [
    {
      "pod_name": "Luke Pod",
      "pod_lead": "Luke Surname",
      "deal_segment_focus": "Hype Deal",
      "members": [
        {
          "name": "Full Name",
          "sf_user_id": "0051g000000XXXAA1",
          "role": "AE",
          "vertical_focus": ["Fintech", "Crypto"]
        }
      ]
    }
  ]
}
```

**How to find SF User IDs:**
Salesforce > Setup > Users > click a user > copy the ID from the URL bar
Format: `0051g000000XXXXXXX` (18 characters)

**Valid roles:** `AE`, `BDR`, `SE`
Only `AE` roles receive primary account ownership. BDRs and SEs are attributed via Opportunity Contact Roles.

**Valid verticals (align with your SF Industry picklist values):**
`Fintech`, `Crypto`, `Enterprise`, `Retail`, `Travel`, `Gaming`, `Marketplace`

---

### STEP 2 — Territory Assignment (Pillar I)

**What it does:**
1. Reads `top_500.csv`
2. Calls Apollo API to enrich accounts with missing firmographics
3. Classifies each account as `Hype Deal` or `Long-term Strategic`
4. Assigns pod ownership using load-balanced vertical matching
5. Upserts `OwnerId`, `Pod_Name__c`, `IC_Owner_Pod__c`, `Deal_Segment__c` to Salesforce

**Time:** ~15-30 min (Apollo rate limits apply — ~0.5s per enrichment call)
**Writes to SF:** ✅ Yes (Account object only)

```bash
# Always dry-run first
python assign_territories.py --dry-run

# Review outputs/unassigned_accounts.csv before proceeding
# Then run live:
python assign_territories.py
```

**Dry-run output to review:**
- Console: assignment summary by pod and segment
- `outputs/unassigned_accounts.csv`: accounts that couldn't be matched

**Unassigned accounts:** These fall into one of two causes:
1. No AE in the matching pod covers that vertical → update `pod_manifest.json`
2. Missing Industry data that Apollo couldn't enrich → manually set `Deal_Segment` in CSV

---

### STEP 3 — MEDDIC Audit (Pillar III — run before Looker)

**What it does:**
1. Queries all open opportunities
2. Scores each against 6 MEDDIC components (weighted, 0–100)
3. Flags opportunities below score 60
4. Writes `MEDDIC_Audit_Score__c`, `MEDDIC_Audit_Flag__c`, `MEDDIC_Missing_Fields__c` back to SF
5. These fields are then available as Looker and Clari filter surfaces

**Time:** ~5 min
**Writes to SF:** ✅ Yes (Opportunity object only)

```bash
# Dry-run first
python meddic_audit.py --dry-run

# Review score distribution in console output, then run live:
python meddic_audit.py
```

**MEDDIC Scoring Weights:**

| Component | SF Field | Weight | Notes |
|---|---|---|---|
| Metrics | `MEDDIC_Metrics__c` | 20 | Quantified business impact |
| Economic Buyer | `MEDDIC_Economic_Buyer__c` | 20 | Named contact, not just title |
| Identify Pain | `MEDDIC_Identify_Pain__c` | 20 | Specific pain, not generic |
| Decision Criteria | `MEDDIC_Decision_Criteria__c` | 15 | Their eval criteria documented |
| Decision Process | `MEDDIC_Decision_Process__c` | 15 | Steps + timeline documented |
| Champion | `MEDDIC_Champion__c` | 10 | Internal advocate identified |

**Threshold logic:**
- Score ≥ 60: Passes to Clari forecast
- Score < 60: Flagged — excluded from Clari by default filter

---

### STEP 4 — Pipeline Hygiene (Pillar III)

**What it does:**
Triages the 18-month pipeline desert into three buckets.
**This script is read-only — it produces CSVs for human review, it does not write to SF.**

**Time:** ~2 min
**Writes to SF:** ❌ No

```bash
python clari_pipeline_hygiene.py
```

**Three output files:**

| File | Action Required |
|---|---|
| `outputs/archive_candidates.csv` | Review → bulk close in SF as Closed Lost |
| `outputs/requalify_candidates.csv` | Send to pod leads — 48hr response window |
| `outputs/h2_high_velocity.csv` | Import as Clari forecast inclusion filter |

**After reviewing outputs — bulk close archive candidates in SF:**
Salesforce > Opportunities list view > filter by IDs in archive CSV > Mass Update > Stage: Closed Lost

**Set Clari inclusion filter:**
Clari > Pipeline > Filters > Add Custom Filter:
```
MEDDIC_Audit_Score__c >= 60
AND CloseDate >= 2025-07-01
AND CloseDate <= 2025-12-31
AND IsClosed = false
```

---

### STEP 5 — Deploy LookML (Pillar II)

**Prerequisites:** Steps 2–4 must be complete so that `Pod_Name__c`, `Deal_Segment__c`, and `MEDDIC_Audit_Score__c` are populated in SF and available in Looker's SF connection.

**Deployment steps:**

```bash
# 1. Copy LookML files to your Looker project directory
cp lookml/*.lkml /path/to/your/looker/project/

# 2. In Looker IDE: validate the project
# Looker > Develop > [Your Project] > Validate LookML

# 3. Deploy to production
# Looker > Develop > Deploy to Production
```

**Key field name assumptions to verify before deploying:**

| LookML Reference | Assumed SF API Name | Verify In |
|---|---|---|
| `role__c` | `Role__c` on Opportunity Contact Role | SF Object Manager |
| `expected_tpv__c` | `Expected_TPV__c` on Opportunity | SF Object Manager |
| `stage_1_entry_date__c` | `Stage_1_Entry_Date__c` on Opportunity | SF Object Manager |
| `pod_name__c` | `Pod_Name__c` on Opportunity | Created in Step 0 |

> **Note on stage velocity fields:** `stage_X_entry_date__c` fields must exist in SF to populate velocity metrics. If you use Salesforce's native Stage History object instead, the DATEDIFF SQL in the LookML views will need to be rewritten as a subquery join. Flag this to your Looker admin before deployment.

---

## Rollout Calendar

| Week | Action | Who | Gate |
|---|---|---|---|
| W1 | Run preflight; create missing SF fields | SF Admin | None |
| W1 | Populate `pod_manifest.json` | You + pod leads | Pod leads confirm IDs |
| W2 | `assign_territories.py --dry-run`; review unassigned CSV | RevOps | Manifest complete |
| W2 | Resolve unassigned accounts; update manifest | RevOps + pod leads | Dry-run output |
| W3 | `assign_territories.py` live run; spot-check 10 SF accounts | RevOps + Admin | Dry-run approved |
| W3 | `meddic_audit.py --dry-run`; review score distribution | RevOps | SF fields live |
| W4 | `meddic_audit.py` live run; review flagged list with CRO | RevOps + CRO | Score distribution signed off |
| W4 | `clari_pipeline_hygiene.py`; review 3 CSVs with pod leads | RevOps + pod leads | MEDDIC scores live |
| W5 | Bulk-close archive candidates; set Clari H2 filter | SF Admin + RevOps | Hygiene CSVs reviewed |
| W6 | Deploy LookML to dev; validate with Looker admin | Looker Admin | All SF fields populated |
| W6 | Go-live: Regional Performance Leaderboard | Looker Admin | LookML validated |

---

## Troubleshooting

**`SalesforceAuthenticationFailed`**
→ Check `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN` in `.env`
→ Confirm `SF_DOMAIN=login` (not `test`) if targeting production

**`Field Pod_Name__c not found on Account`**
→ Field hasn't been created yet. Follow Step 0 field creation table above.

**`Apollo enrichment failed: HTTP 429`**
→ Rate limit hit. Script will auto-retry once after 10s. If persistent, increase `APOLLO_RATE_LIMIT_DELAY` in `assign_territories.py` from `0.5` to `1.0`.

**`Unassigned accounts > 10% of Top 500`**
→ Usually means vertical_focus values in `pod_manifest.json` don't match SF Industry picklist values exactly. Check for capitalisation differences (e.g. `"fintech"` vs `"Fintech"`).

**LookML validation error: `unknown field`**
→ A custom SF field referenced in LookML doesn't exist in your Looker SF connection. Either the field is new (run a Looker PDT rebuild) or the API name differs (check Object Manager).

**Clari not reflecting MEDDIC scores**
→ Clari syncs from SF on a schedule (usually every 4-6 hours). Check Clari > Settings > Integrations > Salesforce > Last Sync timestamp.

---

## Key Contacts for Blockers

| Blocker | Who to contact |
|---|---|
| SF custom field creation | SF Admin (needs System Administrator profile) |
| Looker PDT deployment | Looker Admin (needs `develop` permission) |
| Apollo API key | Apollo account owner |
| Clari filter configuration | Clari Admin or CSM |
| Pod manifest IC User IDs | Pod leads (Luke, Francesco, et al.) |

---

*Generated by Checkout.com NORAM RevOps | Claude Code compatible*
