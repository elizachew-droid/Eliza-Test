Checkout.com NORAM RevOps Automation
Claude Code Execution Guide
Purpose: Three-pillar automation for territory planning, OKR dashboarding, and forecast hygiene.
Target: $100BN TPV run rate | H2 2025
Last updated: 2025

⚠ Read Before Running Anything
This repo contains scripts that write directly to your Salesforce production org.
Two safeguards are built in:

preflight_check.py — validates permissions and field existence before any writes
--dry-run flag on all write scripts — prints what would happen without touching SF

Rule: Never skip preflight. Never skip dry-run on first execution.

Repository Structure
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

Prerequisites
Python Dependencies
bashpip install simple-salesforce pandas requests python-dotenv
Environment Variables
Copy .env.example to .env and populate all values:
bashcp .env.example .env
bash# .env.example — copy to .env and fill in all values

# Salesforce credentials
SF_USERNAME=                  # e.g. john.doe@checkout.com
SF_PASSWORD=                  # Your SF password
SF_SECURITY_TOKEN=            # Setup > My Personal Information > Reset Security Token
SF_DOMAIN=login               # Use 'test' for sandbox, 'login' for production

# Apollo.io
APOLLO_API_KEY=               # Apollo dashboard > Settings > API Keys

# Environment flag (prevents accidental prod writes)
ENVIRONMENT=sandbox           # Change to 'production' only when ready for live run

How to find your SF Security Token:
Salesforce > Avatar (top right) > Settings > My Personal Information > Reset My Security Token
It will be emailed to your SF login address.


Execution Sequence
Follow this order exactly. Each step is a dependency for the next.

STEP 0 — Preflight Check
What it does: Validates SF auth, checks all required custom fields exist, confirms Apollo key is present.
Time: ~30 seconds
Writes to SF: ❌ No
bashpython preflight_check.py
Expected output:
✅ Salesforce authentication: PASSED
✅ Read Account object
✅ Read Opportunity object
✅ Read/Write custom field Account.Pod_Name__c
✅ Read/Write custom field Account.IC_Owner_Pod__c
✅ Read/Write Opportunity.MEDDIC_Audit_Score__c
✅ Apollo API key present

✅ All checks passed. Safe to proceed with write scripts.
If fields are missing: Create them in Salesforce before proceeding.
Go to: Setup > Object Manager > [Account or Opportunity] > Fields & Relationships > New
Field LabelAPI NameTypeObjectPod NamePod_Name__cText(100)AccountIC Owner PodIC_Owner_Pod__cText(100)AccountDeal SegmentDeal_Segment__cPicklist: Hype Deal / Long-term StrategicAccountMEDDIC Audit ScoreMEDDIC_Audit_Score__cNumber(3,0)OpportunityMEDDIC Audit FlagMEDDIC_Audit_Flag__cCheckboxOpportunityMEDDIC Missing FieldsMEDDIC_Missing_Fields__cText Area(255)OpportunityExpected TPVExpected_TPV__cCurrencyOpportunity

STEP 1 — Prepare Your Input Files
1a. Export top_500.csv from Salesforce
Required columns (exact names):
AccountId, Account_Name, Annual_Revenue, Employee_Count, Industry, Deal_Segment

AccountId: Salesforce 18-character Account ID (starts with 001)
Deal_Segment: Optional. If populated, overrides all automation logic. Use: Hype Deal or Long-term Strategic
Leave Annual_Revenue, Employee_Count, Industry blank where unknown — Apollo will fill them

1b. Populate pod_manifest.json
This is the only file that requires manual input from you. It cannot be automated.
json{
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
How to find SF User IDs:
Salesforce > Setup > Users > click a user > copy the ID from the URL bar
Format: 0051g000000XXXXXXX (18 characters)
Valid roles: AE, BDR, SE
Only AE roles receive primary account ownership. BDRs and SEs are attributed via Opportunity Contact Roles.
Valid verticals (align with your SF Industry picklist values):
Fintech, Crypto, Enterprise, Retail, Travel, Gaming, Marketplace

STEP 2 — Territory Assignment (Pillar I)
What it does:

Reads top_500.csv
Calls Apollo API to enrich accounts with missing firmographics
Classifies each account as Hype Deal or Long-term Strategic
Assigns pod ownership using load-balanced vertical matching
Upserts OwnerId, Pod_Name__c, IC_Owner_Pod__c, Deal_Segment__c to Salesforce

Time: ~15-30 min (Apollo rate limits apply — ~0.5s per enrichment call)
Writes to SF: ✅ Yes (Account object only)
bash# Always dry-run first
python assign_territories.py --dry-run

# Review outputs/unassigned_accounts.csv before proceeding
# Then run live:
python assign_territories.py
Dry-run output to review:

Console: assignment summary by pod and segment
outputs/unassigned_accounts.csv: accounts that couldn't be matched

Unassigned accounts: These fall into one of two causes:

No AE in the matching pod covers that vertical → update pod_manifest.json
Missing Industry data that Apollo couldn't enrich → manually set Deal_Segment in CSV


STEP 3 — MEDDIC Audit (Pillar III — run before Looker)
What it does:

Queries all open opportunities
Scores each against 6 MEDDIC components (weighted, 0–100)
Flags opportunities below score 60
Writes MEDDIC_Audit_Score__c, MEDDIC_Audit_Flag__c, MEDDIC_Missing_Fields__c back to SF
These fields are then available as Looker and Clari filter surfaces

Time: ~5 min
Writes to SF: ✅ Yes (Opportunity object only)
bash# Dry-run first
python meddic_audit.py --dry-run

# Review score distribution in console output, then run live:
python meddic_audit.py
MEDDIC Scoring Weights:
ComponentSF FieldWeightNotesMetricsMEDDIC_Metrics__c20Quantified business impactEconomic BuyerMEDDIC_Economic_Buyer__c20Named contact, not just titleIdentify PainMEDDIC_Identify_Pain__c20Specific pain, not genericDecision CriteriaMEDDIC_Decision_Criteria__c15Their eval criteria documentedDecision ProcessMEDDIC_Decision_Process__c15Steps + timeline documentedChampionMEDDIC_Champion__c10Internal advocate identified
Threshold logic:

Score ≥ 60: Passes to Clari forecast
Score < 60: Flagged — excluded from Clari by default filter


STEP 4 — Pipeline Hygiene (Pillar III)
What it does:
Triages the 18-month pipeline desert into three buckets.
This script is read-only — it produces CSVs for human review, it does not write to SF.
Time: ~2 min
Writes to SF: ❌ No
bashpython clari_pipeline_hygiene.py
Three output files:
FileAction Requiredoutputs/archive_candidates.csvReview → bulk close in SF as Closed Lostoutputs/requalify_candidates.csvSend to pod leads — 48hr response windowoutputs/h2_high_velocity.csvImport as Clari forecast inclusion filter
After reviewing outputs — bulk close archive candidates in SF:
Salesforce > Opportunities list view > filter by IDs in archive CSV > Mass Update > Stage: Closed Lost
Set Clari inclusion filter:
Clari > Pipeline > Filters > Add Custom Filter:
MEDDIC_Audit_Score__c >= 60
AND CloseDate >= 2025-07-01
AND CloseDate <= 2025-12-31
AND IsClosed = false

STEP 5 — Deploy LookML (Pillar II)
Prerequisites: Steps 2–4 must be complete so that Pod_Name__c, Deal_Segment__c, and MEDDIC_Audit_Score__c are populated in SF and available in Looker's SF connection.
Deployment steps:
bash# 1. Copy LookML files to your Looker project directory
cp lookml/*.lkml /path/to/your/looker/project/

# 2. In Looker IDE: validate the project
# Looker > Develop > [Your Project] > Validate LookML

# 3. Deploy to production
# Looker > Develop > Deploy to Production
Key field name assumptions to verify before deploying:
LookML ReferenceAssumed SF API NameVerify Inrole__cRole__c on Opportunity Contact RoleSF Object Managerexpected_tpv__cExpected_TPV__c on OpportunitySF Object Managerstage_1_entry_date__cStage_1_Entry_Date__c on OpportunitySF Object Managerpod_name__cPod_Name__c on OpportunityCreated in Step 0

Note on stage velocity fields: stage_X_entry_date__c fields must exist in SF to populate velocity metrics. If you use Salesforce's native Stage History object instead, the DATEDIFF SQL in the LookML views will need to be rewritten as a subquery join. Flag this to your Looker admin before deployment.


Rollout Calendar
WeekActionWhoGateW1Run preflight; create missing SF fieldsSF AdminNoneW1Populate pod_manifest.jsonYou + pod leadsPod leads confirm IDsW2assign_territories.py --dry-run; review unassigned CSVRevOpsManifest completeW2Resolve unassigned accounts; update manifestRevOps + pod leadsDry-run outputW3assign_territories.py live run; spot-check 10 SF accountsRevOps + AdminDry-run approvedW3meddic_audit.py --dry-run; review score distributionRevOpsSF fields liveW4meddic_audit.py live run; review flagged list with CRORevOps + CROScore distribution signed offW4clari_pipeline_hygiene.py; review 3 CSVs with pod leadsRevOps + pod leadsMEDDIC scores liveW5Bulk-close archive candidates; set Clari H2 filterSF Admin + RevOpsHygiene CSVs reviewedW6Deploy LookML to dev; validate with Looker adminLooker AdminAll SF fields populatedW6Go-live: Regional Performance LeaderboardLooker AdminLookML validated

Troubleshooting
SalesforceAuthenticationFailed
→ Check SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN in .env
→ Confirm SF_DOMAIN=login (not test) if targeting production
Field Pod_Name__c not found on Account
→ Field hasn't been created yet. Follow Step 0 field creation table above.
Apollo enrichment failed: HTTP 429
→ Rate limit hit. Script will auto-retry once after 10s. If persistent, increase APOLLO_RATE_LIMIT_DELAY in assign_territories.py from 0.5 to 1.0.
Unassigned accounts > 10% of Top 500
→ Usually means vertical_focus values in pod_manifest.json don't match SF Industry picklist values exactly. Check for capitalisation differences (e.g. "fintech" vs "Fintech").
LookML validation error: unknown field
→ A custom SF field referenced in LookML doesn't exist in your Looker SF connection. Either the field is new (run a Looker PDT rebuild) or the API name differs (check Object Manager).
Clari not reflecting MEDDIC scores
→ Clari syncs from SF on a schedule (usually every 4-6 hours). Check Clari > Settings > Integrations > Salesforce > Last Sync timestamp.

Key Contacts for Blockers
BlockerWho to contactSF custom field creationSF Admin (needs System Administrator profile)Looker PDT deploymentLooker Admin (needs develop permission)Apollo API keyApollo account ownerClari filter configurationClari Admin or CSMPod manifest IC User IDsPod leads (Luke, Francesco, et al.)
