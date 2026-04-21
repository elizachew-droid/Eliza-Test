# NORAM Sales Velocity Dashboard — Google Apps Script Setup

## Files
| File | Purpose |
|---|---|
| `Code.gs` | Server-side: Salesforce REST API fetch, pagination, doGet() |
| `Index.html` | Client-side SPA: all filtering, charts, tables |
| `appsscript.json` | Manifest: webapp config |

---

## Deploy Steps

### 1. Create the GAS Project
1. Go to [script.google.com](https://script.google.com) → **New Project**
2. Rename to `NORAM Sales Velocity Dashboard`

### 2. Add the Files
**Replace the default `Code.gs`** with the contents of `Code.gs`

**Add `Index.html`:**
- Click **+** next to Files → **HTML**
- Name it exactly `Index` (no extension)
- Paste the contents of `Index.html`

**Replace `appsscript.json`:**
- Click **Project Settings** (gear icon) → tick **Show "appsscript.json"**
- Go back to Editor, open `appsscript.json`, replace with the file contents

### 3. Set Script Properties (your Salesforce credentials)
1. **Project Settings** (gear) → **Script Properties** → **Add script property**
2. Add both:

| Property | Value |
|---|---|
| `SF_INSTANCE_URL` | `https://checkout.my.salesforce.com` |
| `SF_ACCESS_TOKEN` | Your `sid` cookie from DevTools |

> The token expires with your browser session (~2hrs). When it does, update
> `SF_ACCESS_TOKEN` in Script Properties and re-run.

### 4. Deploy as Web App
1. **Deploy** → **New Deployment**
2. Type: **Web App**
3. Execute as: **Me**
4. Who has access: **Anyone** (or restrict to your org)
5. Click **Deploy** → copy the Web App URL

### 5. Open the Dashboard
Paste the Web App URL in a browser. The dashboard loads Salesforce data on
each visit and processes everything client-side.

---

## Updating the Token
When `SF_ACCESS_TOKEN` expires:
1. Log in to Salesforce in Chrome
2. DevTools → Application → Cookies → `checkout.my.salesforce.com`
3. Copy `sid` value
4. GAS Editor → Project Settings → Script Properties → update `SF_ACCESS_TOKEN`
5. No redeployment needed — the change takes effect immediately

---

## NORAM Filter Logic
Implemented in both SOQL (server) and JavaScript (client validation):
```
Type == "New Business"
AND (
  Account_Territory__c        LIKE '%NORAM%'
  OR Record_Owner_Sales_Territory__c  LIKE '%NORAM%'
  OR Second_Opp_Owner_Sales_Territory__c LIKE '%NORAM%'
  OR Acquiring_Channel__c     == 'CRB(US)'
)
```

## Stage Matching
The dashboard matches sub-stage values flexibly (case-insensitive):
| Stage | Matched values |
|---|---|
| E1 | `e1`, `explore` |
| P1 | `p1`, `propose` |
| T1 | `t1`, `trade` |
| H1 | `h1`, `handover` |

If your org uses different picklist values, update `STAGE_VALUES` in `Index.html`.

## Tier Thresholds (Leaderboard)
Red cell  = gap > 14 days
Amber cell = gap 8–14 days
Green = ≤ 7 days
