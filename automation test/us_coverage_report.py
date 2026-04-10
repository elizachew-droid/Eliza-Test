#!/usr/bin/env python3
"""
us_coverage_report.py
---------------------
Generates a self-contained interactive HTML dashboard showing:
  - Gold / Silver / Bronze tier tables (top 20 accounts each by revenue)
  - Sub-industry filter toggles across all tiers
  - Pie chart: East Coast / West Coast / Open / Canada
  - All charts built with Chart.js (no Python chart dependencies needed)

Usage:
    python us_coverage_report.py
    python us_coverage_report.py --output ./output/us_coverage_report.html
    python us_coverage_report.py --sub-vertical-field Sub_Vertical__c --psp-field PSP__c
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sf_auth import get_salesforce_client

logging.basicConfig(format="%(levelname)-8s %(message)s", level=logging.INFO)

# ---------------------------------------------------------------------------
# Region mapping  (East Coast / West Coast / Canada / Open)
# ---------------------------------------------------------------------------

EAST_COAST  = {"ME","NH","VT","MA","RI","CT","NY","NJ","PA","DE","MD","DC",
               "VA","WV","NC","SC","GA","FL"}
WEST_COAST  = {"WA","OR","CA","NV","AZ"}
CANADA_COUNTRIES = {"CA","CAN","CANADA"}

def get_region(billing_state: str, billing_country: str) -> str:
    state   = (billing_state   or "").strip().upper()
    country = (billing_country or "").strip().upper()
    if country in CANADA_COUNTRIES:
        return "Canada"
    if state in EAST_COAST:
        return "East Coast"
    if state in WEST_COAST:
        return "West Coast"
    return "Open"

# ---------------------------------------------------------------------------
# Tier classification  (by AnnualRevenue)
# ---------------------------------------------------------------------------

def get_tier(revenue) -> str:
    rev = float(revenue or 0)
    if rev >= 100_000_000:
        return "Gold"
    if rev >= 10_000_000:
        return "Silver"
    return "Bronze"

TIER_ORDER  = ["Gold", "Silver", "Bronze"]
TIER_EMOJI  = {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}
TIER_COLOUR = {"Gold": "#F0B429", "Silver": "#8b949e", "Bronze": "#CD7F32"}

# ---------------------------------------------------------------------------
# Salesforce query
# ---------------------------------------------------------------------------

def _try_soql(sf, soql: str):
    try:
        return sf.query_all(soql).get("records", [])
    except Exception as exc:
        return None, str(exc)


def fetch_accounts(sf, sub_vertical_field: str, psp_field: str) -> list[dict]:
    """
    Query accounts.  If custom fields don't exist yet, falls back
    gracefully to standard fields only.
    """
    base_fields = "Id, Name, Owner.Name, Website, BillingState, BillingCountry, AnnualRevenue"
    custom      = f", {sub_vertical_field}, {psp_field}"

    # Try with custom fields first
    soql = (
        f"SELECT {base_fields}{custom} FROM Account "
        f"WHERE BillingCountry IN "
        f"('US','USA','United States','CA','CAN','Canada') "
        f"ORDER BY AnnualRevenue DESC NULLS LAST"
    )
    logging.info("Querying Salesforce accounts…")
    try:
        records = sf.query_all(soql).get("records", [])
        logging.info("Fetched %d account(s) (with custom fields).", len(records))
        return records, sub_vertical_field, psp_field
    except Exception:
        pass

    # Fallback: standard fields only
    logging.warning(
        "Custom fields not found (%s, %s) — querying standard fields only.",
        sub_vertical_field, psp_field,
    )
    soql_fallback = (
        f"SELECT {base_fields} FROM Account "
        f"WHERE BillingCountry IN "
        f"('US','USA','United States','CA','CAN','Canada') "
        f"ORDER BY AnnualRevenue DESC NULLS LAST"
    )
    records = sf.query_all(soql_fallback).get("records", [])
    logging.info("Fetched %d account(s) (standard fields only).", len(records))
    return records, None, None


# ---------------------------------------------------------------------------
# Data transformation
# ---------------------------------------------------------------------------

def transform(records: list[dict],
              sub_vertical_field: str | None,
              psp_field: str | None) -> list[dict]:
    out = []
    for r in records:
        owner   = (r.get("Owner") or {}).get("Name") or "—"
        website = r.get("Website") or "—"
        rev     = float(r.get("AnnualRevenue") or 0)
        sub_v   = (r.get(sub_vertical_field) if sub_vertical_field else None) or "—"
        psp     = (r.get(psp_field)           if psp_field          else None) or "—"
        state   = r.get("BillingState")   or ""
        country = r.get("BillingCountry") or ""

        out.append({
            "name":     r.get("Name") or "—",
            "owner":    owner,
            "website":  website,
            "sub_v":    sub_v,
            "revenue":  rev,
            "psp":      psp,
            "tier":     get_tier(rev),
            "region":   get_region(state, country),
        })
    return out


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

def _fmt_rev(v: float) -> str:
    if v >= 1_000_000_000: return f"${v/1_000_000_000:.1f}B"
    if v >= 1_000_000:     return f"${v/1_000_000:.1f}M"
    if v >= 1_000:         return f"${v/1_000:.0f}K"
    return f"${v:.0f}" if v else "—"

def _esc(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def build_dashboard(accounts: list[dict]) -> str:
    # Collect all sub-industries for filter buttons
    sub_verticals = sorted({a["sub_v"] for a in accounts if a["sub_v"] != "—"})

    # Region counts for pie chart
    region_counts: dict[str, int] = defaultdict(int)
    for a in accounts:
        region_counts[a["region"]] += 1
    region_order  = ["East Coast", "West Coast", "Open", "Canada"]
    region_labels = json.dumps([r for r in region_order if r in region_counts])
    region_data   = json.dumps([region_counts.get(r, 0) for r in region_order if r in region_counts])
    region_colours= json.dumps(["#4C9BE8", "#E8834C", "#4CE8A0", "#B04CE8"])

    # Tier data for bar chart
    tier_counts   = {t: sum(1 for a in accounts if a["tier"] == t) for t in TIER_ORDER}
    tier_labels   = json.dumps(TIER_ORDER)
    tier_data     = json.dumps([tier_counts.get(t, 0) for t in TIER_ORDER])
    tier_colours  = json.dumps([TIER_COLOUR[t] for t in TIER_ORDER])

    # Build per-tier top-20 tables
    tier_tables_html = ""
    for tier in TIER_ORDER:
        tier_accounts = [a for a in accounts if a["tier"] == tier]
        tier_accounts.sort(key=lambda x: -x["revenue"])
        top20 = tier_accounts[:20]

        rows = ""
        for i, a in enumerate(top20, 1):
            sub_v_attr = _esc(a["sub_v"])
            rows += f"""
            <tr class="account-row" data-subv="{sub_v_attr}">
              <td class="rank">{i}</td>
              <td class="name">{_esc(a['name'])}</td>
              <td>{_esc(a['owner'])}</td>
              <td><a href="https://{_esc(a['website'])}" target="_blank" class="link">{_esc(a['website'])}</a></td>
              <td><span class="pill subv-pill">{_esc(a['sub_v'])}</span></td>
              <td class="rev">{_fmt_rev(a['revenue'])}</td>
              <td>{_esc(a['psp'])}</td>
            </tr>"""

        colour = TIER_COLOUR[tier]
        emoji  = TIER_EMOJI[tier]
        total_rev = sum(a["revenue"] for a in tier_accounts)

        tier_tables_html += f"""
      <div class="tier-section" id="tier-{tier.lower()}">
        <div class="tier-header" onclick="toggleTier('{tier.lower()}')">
          <div class="tier-title">
            <span class="tier-badge" style="background:{colour}22;color:{colour};border-color:{colour}44">{emoji} {tier}</span>
            <span class="tier-meta">{len(tier_accounts)} accounts · {_fmt_rev(total_rev)} total ARR</span>
          </div>
          <span class="chevron" id="chevron-{tier.lower()}">▼</span>
        </div>
        <div class="tier-body" id="body-{tier.lower()}">
          <div class="table-wrap">
            <table class="acct-table" id="table-{tier.lower()}">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Account Name</th>
                  <th>Account Owner</th>
                  <th>Website</th>
                  <th>Sub-Vertical</th>
                  <th>Revenue</th>
                  <th>RevOps — PSP Estimate</th>
                </tr>
              </thead>
              <tbody>
                {rows}
              </tbody>
            </table>
          </div>
        </div>
      </div>"""

    # Sub-industry filter buttons
    filter_btns = '<button class="filter-btn active" onclick="setFilter(\'all\', this)">All</button>\n'
    for sv in sub_verticals:
        filter_btns += f'      <button class="filter-btn" onclick="setFilter(\'{_esc(sv)}\', this)">{_esc(sv)}</button>\n'

    total_accounts = len(accounts)
    total_arr = _fmt_rev(sum(a["revenue"] for a in accounts))
    generated = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NORAM Account Coverage · Checkout.com RevOps</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#0d1117;--surface:#161b22;--surface2:#1c2128;--border:#30363d;
  --text:#e6edf3;--muted:#8b949e;--accent:#4C9BE8;
  --gold:#F0B429;--silver:#8b949e;--bronze:#CD7F32;
  --green:#2EA44F;--red:#DA3633;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:28px 32px;}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
/* Header */
.header{{margin-bottom:28px}}
.header h1{{font-size:20px;font-weight:700;margin-bottom:4px}}
.header .sub{{color:var(--muted);font-size:13px}}
/* KPIs */
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:28px}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 22px;min-width:140px}}
.kpi .val{{font-size:24px;font-weight:700;color:var(--accent)}}
.kpi .lbl{{font-size:11px;color:var(--muted);margin-top:3px;text-transform:uppercase;letter-spacing:.05em}}
/* Charts row */
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px}}
.chart-card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px}}
.chart-card h3{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:16px}}
.chart-card canvas{{max-height:260px}}
/* Filters */
.filter-section{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 20px;margin-bottom:20px}}
.filter-section h3{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}}
.filter-row{{display:flex;flex-wrap:wrap;gap:8px}}
.filter-btn{{background:var(--surface2);border:1px solid var(--border);color:var(--muted);border-radius:20px;padding:5px 14px;font-size:12px;cursor:pointer;transition:all .15s}}
.filter-btn:hover{{border-color:var(--accent);color:var(--text)}}
.filter-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}}
/* Tier sections */
.tier-section{{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}}
.tier-header{{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;cursor:pointer;user-select:none}}
.tier-header:hover{{background:var(--surface2)}}
.tier-title{{display:flex;align-items:center;gap:14px}}
.tier-badge{{border:1px solid;border-radius:20px;padding:4px 14px;font-size:13px;font-weight:700}}
.tier-meta{{font-size:13px;color:var(--muted)}}
.chevron{{color:var(--muted);transition:transform .2s;font-size:12px}}
.tier-body{{padding:0 20px 20px}}
.table-wrap{{overflow-x:auto}}
.acct-table{{width:100%;border-collapse:collapse;font-size:13px}}
.acct-table th{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}}
.acct-table td{{padding:9px 10px;border-bottom:1px solid var(--border);vertical-align:middle}}
.acct-table tr:last-child td{{border-bottom:none}}
.acct-table tr.hidden{{display:none}}
.rank{{color:var(--muted);font-size:12px;width:28px}}
.name{{font-weight:600;max-width:200px}}
.rev{{font-weight:600;color:var(--accent);text-align:right;white-space:nowrap}}
.pill{{display:inline-block;border-radius:12px;padding:2px 9px;font-size:11px;font-weight:500;background:rgba(76,155,232,.15);color:var(--accent);border:1px solid rgba(76,155,232,.3)}}
.link{{font-size:12px;color:var(--muted)}}
.footer{{color:var(--muted);font-size:11px;margin-top:24px;text-align:center}}
@media(max-width:700px){{.charts-row{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="header">
  <h1>NORAM Account Coverage Dashboard</h1>
  <p class="sub">Checkout.com RevOps · Generated {generated}</p>
</div>

<div class="kpis">
  <div class="kpi"><div class="val">{total_accounts}</div><div class="lbl">Total Accounts</div></div>
  <div class="kpi"><div class="val" style="color:var(--gold)">{tier_counts.get('Gold',0)}</div><div class="lbl">Gold Accounts</div></div>
  <div class="kpi"><div class="val" style="color:var(--silver)">{tier_counts.get('Silver',0)}</div><div class="lbl">Silver Accounts</div></div>
  <div class="kpi"><div class="val" style="color:var(--bronze)">{tier_counts.get('Bronze',0)}</div><div class="lbl">Bronze Accounts</div></div>
  <div class="kpi"><div class="val">{total_arr}</div><div class="lbl">Total ARR</div></div>
</div>

<div class="charts-row">
  <div class="chart-card">
    <h3>Accounts by Region</h3>
    <canvas id="pieChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>Accounts by Tier</h3>
    <canvas id="tierChart"></canvas>
  </div>
</div>

<div class="filter-section">
  <h3>Filter by Sub-Industry</h3>
  <div class="filter-row">
    {filter_btns}
  </div>
</div>

{tier_tables_html}

<p class="footer">Tier classification: Gold ≥ $100M ARR · Silver $10M–$100M · Bronze &lt; $10M · Checkout.com NORAM RevOps</p>

<script>
// ── Charts ──────────────────────────────────────────────────────────────────
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';

new Chart(document.getElementById('pieChart'), {{
  type: 'doughnut',
  data: {{
    labels: {region_labels},
    datasets: [{{
      data: {region_data},
      backgroundColor: {region_colours},
      borderColor: '#0d1117',
      borderWidth: 3,
      hoverOffset: 6,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{ padding: 16, font: {{ size: 12 }}, color: '#e6edf3' }}
      }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.label}}: ${{ctx.parsed}} accounts (${{Math.round(ctx.parsed/ctx.dataset.data.reduce((a,b)=>a+b,0)*100)}}%)`
        }}
      }}
    }}
  }}
}});

new Chart(document.getElementById('tierChart'), {{
  type: 'bar',
  data: {{
    labels: {tier_labels},
    datasets: [{{
      data: {tier_data},
      backgroundColor: {tier_colours},
      borderRadius: 6,
      borderSkipped: false,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ color: '#e6edf3', font: {{ size: 12 }} }} }},
      y: {{ grid: {{ color: '#30363d' }}, ticks: {{ color: '#8b949e' }} }}
    }}
  }}
}});

// ── Tier collapse ────────────────────────────────────────────────────────────
function toggleTier(tier) {{
  const body    = document.getElementById('body-' + tier);
  const chevron = document.getElementById('chevron-' + tier);
  const open    = body.style.display !== 'none';
  body.style.display    = open ? 'none' : 'block';
  chevron.style.transform = open ? 'rotate(-90deg)' : 'rotate(0deg)';
}}

// ── Sub-industry filter ──────────────────────────────────────────────────────
let activeFilter = 'all';

function setFilter(value, btn) {{
  activeFilter = value;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilter();
}}

function applyFilter() {{
  document.querySelectorAll('.account-row').forEach(row => {{
    if (activeFilter === 'all') {{
      row.classList.remove('hidden');
    }} else {{
      row.classList.toggle('hidden', row.dataset.subv !== activeFilter);
    }}
  }});
  // Update tier counts after filter
  ['gold','silver','bronze'].forEach(tier => {{
    const table   = document.getElementById('table-' + tier);
    if (!table) return;
    const visible = table.querySelectorAll('.account-row:not(.hidden)').length;
    const meta    = document.querySelector('#tier-' + tier + ' .tier-meta');
    if (meta) {{
      const total = table.querySelectorAll('.account-row').length;
      meta.textContent = activeFilter === 'all'
        ? meta.dataset.orig
        : visible + ' matching · ' + total + ' total';
      if (!meta.dataset.orig) meta.dataset.orig = meta.textContent;
    }}
  }});
}}

// Store originals on load
document.querySelectorAll('.tier-meta').forEach(m => m.dataset.orig = m.textContent);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the NORAM account coverage dashboard."
    )
    parser.add_argument("--sub-vertical-field",
                        default=os.getenv("SF_SUB_VERTICAL_FIELD", "Sub_Vertical__c"))
    parser.add_argument("--psp-field",
                        default=os.getenv("SF_PSP_FIELD", "PSP__c"))
    parser.add_argument("--output",
                        default="./output/us_coverage_report.html")
    args = parser.parse_args()

    sf = get_salesforce_client()
    records, sv_field, psp_field = fetch_accounts(sf, args.sub_vertical_field, args.psp_field)

    if not records:
        logging.error("No records returned.")
        sys.exit(1)

    accounts = transform(records, sv_field, psp_field)
    html     = build_dashboard(accounts)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    # Console summary
    from collections import Counter
    tiers = Counter(a["tier"] for a in accounts)
    regions = Counter(a["region"] for a in accounts)
    print(f"\nTotal accounts : {len(accounts)}")
    for t in ["Gold","Silver","Bronze"]:
        print(f"  {t:<8} : {tiers[t]}")
    print()
    for r in ["East Coast","West Coast","Open","Canada"]:
        print(f"  {r:<12} : {regions[r]}")
    print(f"\nDashboard saved → {out.resolve()}\n")


if __name__ == "__main__":
    main()
