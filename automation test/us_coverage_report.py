#!/usr/bin/env python3
"""
us_coverage_report.py
---------------------
Queries Salesforce for all US accounts from the Eliza Test report base,
maps them to US regions, measures owner coverage, and generates a
self-contained HTML report with interactive charts.

Usage:
    python us_coverage_report.py
    python us_coverage_report.py --output ./output/us_coverage_report.html
    python us_coverage_report.py --source-report 00OVk00000KYxtNMAT
"""

import argparse
import base64
import io
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
# US Region mapping
# ---------------------------------------------------------------------------

STATE_TO_REGION = {
    # Northeast
    "ME": "Northeast", "NH": "Northeast", "VT": "Northeast", "MA": "Northeast",
    "RI": "Northeast", "CT": "Northeast", "NY": "Northeast", "NJ": "Northeast",
    "PA": "Northeast",
    # Southeast
    "DE": "Southeast", "MD": "Southeast", "DC": "Southeast", "VA": "Southeast",
    "WV": "Southeast", "NC": "Southeast", "SC": "Southeast", "GA": "Southeast",
    "FL": "Southeast", "AL": "Southeast", "MS": "Southeast", "TN": "Southeast",
    "KY": "Southeast",
    # Midwest
    "OH": "Midwest", "IN": "Midwest", "IL": "Midwest", "MI": "Midwest",
    "WI": "Midwest", "MN": "Midwest", "IA": "Midwest", "MO": "Midwest",
    "ND": "Midwest", "SD": "Midwest", "NE": "Midwest", "KS": "Midwest",
    # Southwest
    "TX": "Southwest", "OK": "Southwest", "NM": "Southwest", "AZ": "Southwest",
    # West
    "CO": "West", "WY": "West", "MT": "West", "ID": "West", "WA": "West",
    "OR": "West", "CA": "West", "NV": "West", "UT": "West", "AK": "West",
    "HI": "West",
}

REGION_ORDER   = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
REGION_COLOURS = {
    "Northeast": "#4C9BE8",
    "Southeast": "#E8834C",
    "Midwest":   "#4CE8A0",
    "Southwest": "#E8D44C",
    "West":      "#B04CE8",
}

# ---------------------------------------------------------------------------
# Salesforce query
# ---------------------------------------------------------------------------

def fetch_accounts(sf, source_report_id: str | None) -> list[dict]:
    """
    If a source report ID is provided, run that report via the Analytics API
    to stay in sync with its filters.  Otherwise fall back to a direct SOQL
    query of all US accounts.
    """
    if source_report_id:
        return _fetch_from_report(sf, source_report_id)
    return _fetch_via_soql(sf)


def _fetch_from_report(sf, report_id: str) -> list[dict]:
    """Run the existing Salesforce report and parse its fact map into records."""
    logging.info("Running source report %s via Analytics API…", report_id)
    try:
        url = f"{sf.base_url}analytics/reports/{report_id}?includeDetails=true"
        resp = sf.session.get(url, headers={"Authorization": f"Bearer {sf.session_id}"})
        if resp.status_code != 200:
            logging.warning(
                "Analytics API returned %s — falling back to SOQL. Detail: %s",
                resp.status_code, resp.text[:200],
            )
            return _fetch_via_soql(sf)

        data = resp.json()
        fact_map = data.get("factMap", {})
        col_info = (
            data.get("reportExtendedMetadata", {})
                .get("detailColumnInfo", {})
        )
        columns = data.get("reportMetadata", {}).get("detailColumns", [])

        records = []
        for key, section in fact_map.items():
            for row in section.get("rows", []):
                record: dict = {}
                for i, cell in enumerate(row.get("dataCells", [])):
                    if i < len(columns):
                        record[columns[i]] = cell.get("label") or cell.get("value")
                records.append(record)

        logging.info("Report returned %d row(s).", len(records))

        # Map common column names to standard keys expected downstream
        normalised = []
        for r in records:
            normalised.append({
                "Name":           _find(r, ["Account Name", "NAME", "ACCOUNT_NAME", "Name"]),
                "BillingState":   _find(r, ["Billing State/Province", "BILLING_STATE", "BillingState"]),
                "BillingCountry": _find(r, ["Billing Country", "BILLING_COUNTRY", "BillingCountry"]),
                "AnnualRevenue":  _parse_currency(_find(r, ["Annual Revenue", "ANNUAL_REVENUE", "AnnualRevenue"])),
                "OwnerName":      _find(r, ["Account Owner", "OWNER_NAME", "Owner Name"]),
                "raw":            r,
            })
        return normalised

    except Exception as exc:
        logging.warning("Report run failed (%s) — falling back to SOQL.", exc)
        return _fetch_via_soql(sf)


def _fetch_via_soql(sf) -> list[dict]:
    logging.info("Querying US accounts via SOQL…")
    soql = (
        "SELECT Id, Name, BillingState, BillingCountry, AnnualRevenue, Owner.Name "
        "FROM Account "
        "WHERE BillingCountry IN ('US', 'USA', 'United States') "
        "ORDER BY AnnualRevenue DESC NULLS LAST"
    )
    result = sf.query_all(soql)
    records = result.get("records", [])
    logging.info("SOQL returned %d account(s).", len(records))
    return [
        {
            "Name":           r.get("Name"),
            "BillingState":   r.get("BillingState"),
            "BillingCountry": r.get("BillingCountry"),
            "AnnualRevenue":  r.get("AnnualRevenue") or 0,
            "OwnerName":      (r.get("Owner") or {}).get("Name", "Unassigned"),
        }
        for r in records
    ]


def _find(d: dict, keys: list[str]):
    for k in keys:
        if k in d:
            return d[k]
    # partial match fallback
    for k in d:
        for target in keys:
            if target.lower() in k.lower():
                return d[k]
    return None


def _parse_currency(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = str(val).replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(records: list[dict]) -> dict:
    region_counts:   dict[str, int]   = defaultdict(int)
    region_revenue:  dict[str, float] = defaultdict(float)
    region_covered:  dict[str, int]   = defaultdict(int)   # has an owner
    region_accounts: dict[str, list]  = defaultdict(list)
    state_counts:    dict[str, int]   = defaultdict(int)
    no_state = 0

    for r in records:
        state = (r.get("BillingState") or "").strip().upper()
        # Accept full state names by converting to abbreviation lookup
        region = STATE_TO_REGION.get(state, "Unknown")

        if region == "Unknown":
            no_state += 1
        else:
            region_counts[region]  += 1
            region_revenue[region] += r.get("AnnualRevenue") or 0
            state_counts[state]    += 1
            owner = r.get("OwnerName") or ""
            if owner and owner.lower() not in ("", "none", "unassigned"):
                region_covered[region] += 1
            region_accounts[region].append(r)

    return {
        "region_counts":   dict(region_counts),
        "region_revenue":  dict(region_revenue),
        "region_covered":  dict(region_covered),
        "region_accounts": dict(region_accounts),
        "state_counts":    dict(state_counts),
        "no_state":        no_state,
        "total":           len(records),
    }


# ---------------------------------------------------------------------------
# Chart generation (matplotlib → base64 PNG)
# ---------------------------------------------------------------------------

def _chart_to_b64(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


def make_charts(agg: dict) -> dict[str, str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        logging.warning("matplotlib not installed — charts skipped. Run: pip install matplotlib")
        return {}

    charts = {}
    regions = [r for r in REGION_ORDER if r in agg["region_counts"]]
    counts  = [agg["region_counts"].get(r, 0)   for r in regions]
    revenues = [agg["region_revenue"].get(r, 0)  for r in regions]
    covered  = [agg["region_covered"].get(r, 0)  for r in regions]
    uncovered = [counts[i] - covered[i] for i in range(len(regions))]
    colours  = [REGION_COLOURS[r] for r in regions]

    BG = "#0d1117"
    TEXT = "#e6edf3"
    GRID = "#30363d"

    def _style(ax, title):
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.set_title(title, color=TEXT, fontsize=12, pad=10)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.yaxis.label.set_color(TEXT)
        ax.xaxis.label.set_color(TEXT)
        ax.grid(axis="y", color=GRID, linewidth=0.5, linestyle="--")
        ax.set_axisbelow(True)

    # --- Chart 1: Account count by region ---
    fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
    bars = ax.bar(regions, counts, color=colours, edgecolor=BG, linewidth=0.5)
    for bar, val in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                str(val), ha="center", va="bottom", color=TEXT, fontsize=9)
    _style(ax, "Account Count by US Region")
    ax.set_ylabel("Accounts")
    charts["count_bar"] = _chart_to_b64(fig)

    # --- Chart 2: Revenue by region ---
    rev_m = [r / 1_000_000 for r in revenues]
    fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
    bars = ax.bar(regions, rev_m, color=colours, edgecolor=BG, linewidth=0.5)
    for bar, val in zip(bars, rev_m):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f"${val:.0f}M", ha="center", va="bottom", color=TEXT, fontsize=8)
    _style(ax, "Total Annual Revenue by US Region ($M)")
    ax.set_ylabel("Revenue ($M)")
    charts["revenue_bar"] = _chart_to_b64(fig)

    # --- Chart 3: Coverage stacked bar ---
    fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
    x = range(len(regions))
    b1 = ax.bar(x, covered, color="#2EA44F", label="Covered", edgecolor=BG, linewidth=0.5)
    b2 = ax.bar(x, uncovered, bottom=covered, color="#DA3633",
                label="Uncovered", edgecolor=BG, linewidth=0.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(regions)
    for i, (cov, tot) in enumerate(zip(covered, counts)):
        pct = f"{100*cov/tot:.0f}%" if tot else "—"
        ax.text(i, tot + 0.3, pct, ha="center", va="bottom", color=TEXT, fontsize=8)
    legend = ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=TEXT, fontsize=9)
    _style(ax, "Owner Coverage by Region (Covered vs Uncovered)")
    ax.set_ylabel("Accounts")
    charts["coverage_bar"] = _chart_to_b64(fig)

    # --- Chart 4: Pie — share of accounts ---
    fig, ax = plt.subplots(figsize=(6, 5), facecolor=BG)
    wedges, texts, autotexts = ax.pie(
        counts, labels=regions, colors=colours,
        autopct="%1.1f%%", startangle=140,
        textprops={"color": TEXT, "fontsize": 9},
        wedgeprops={"edgecolor": BG, "linewidth": 1},
    )
    for at in autotexts:
        at.set_color(BG)
        at.set_fontsize(8)
    ax.set_title("Account Share by Region", color=TEXT, fontsize=12, pad=10)
    charts["pie"] = _chart_to_b64(fig)

    return charts


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>US Account Coverage — Eliza Test</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #4C9BE8;
    --green: #2EA44F; --red: #DA3633; --yellow: #E8D44C;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 32px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 13px; margin-bottom: 32px; }}
  .kpi-row {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px 28px; min-width: 160px; }}
  .kpi .value {{ font-size: 28px; font-weight: 700; color: var(--accent); }}
  .kpi .label {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; }}
  .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .chart-card img {{ width: 100%; border-radius: 4px; }}
  .chart-card h3 {{ font-size: 13px; color: var(--muted); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .table-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 32px; overflow-x: auto; }}
  .table-card h2 {{ font-size: 16px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  tr:last-child td {{ border-bottom: none; }}
  .bar-inline {{ display: inline-block; background: var(--accent); height: 8px; border-radius: 4px; vertical-align: middle; margin-right: 8px; }}
  .pill {{ display: inline-block; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 600; }}
  .pill-green {{ background: rgba(46,164,79,0.2); color: var(--green); }}
  .pill-red {{ background: rgba(218,54,51,0.2); color: var(--red); }}
  .pill-yellow {{ background: rgba(232,212,76,0.2); color: var(--yellow); }}
  .footer {{ color: var(--muted); font-size: 11px; margin-top: 16px; }}
  @media (max-width: 768px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<h1>US Account Coverage Report</h1>
<p class="subtitle">Source: Eliza Test · Generated {generated_at}</p>

<div class="kpi-row">
  <div class="kpi"><div class="value">{total_accounts}</div><div class="label">Total Accounts</div></div>
  <div class="kpi"><div class="value">{regions_active}</div><div class="label">Active Regions</div></div>
  <div class="kpi"><div class="value">{coverage_pct}%</div><div class="label">Owner Coverage</div></div>
  <div class="kpi"><div class="value">{total_revenue}</div><div class="label">Total ARR</div></div>
  <div class="kpi"><div class="value">{uncovered_count}</div><div class="label">Uncovered Accounts</div></div>
</div>

<div class="charts-grid">
  <div class="chart-card">
    <h3>Account Count by Region</h3>
    {count_bar_img}
  </div>
  <div class="chart-card">
    <h3>Revenue Distribution</h3>
    {revenue_bar_img}
  </div>
  <div class="chart-card">
    <h3>Owner Coverage by Region</h3>
    {coverage_bar_img}
  </div>
  <div class="chart-card">
    <h3>Account Share</h3>
    {pie_img}
  </div>
</div>

<div class="table-card">
  <h2>Regional Breakdown</h2>
  <table>
    <thead>
      <tr>
        <th>Region</th>
        <th>Accounts</th>
        <th>Share</th>
        <th>Covered</th>
        <th>Coverage %</th>
        <th>Total ARR</th>
        <th>Avg ARR / Account</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</div>

{state_table}

<p class="footer">Generated by us_coverage_report.py · Checkout.com NORAM RevOps</p>
</body>
</html>"""


def _img_tag(b64: str) -> str:
    return f'<img src="data:image/png;base64,{b64}" alt="chart">' if b64 else "<p style='color:var(--muted)'>Chart unavailable</p>"


def _revenue_fmt(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}" if val else "—"


def build_html(agg: dict, charts: dict) -> str:
    total = agg["total"]
    total_covered = sum(agg["region_covered"].get(r, 0) for r in agg["region_counts"])
    uncovered = total - total_covered - agg["no_state"]
    coverage_pct = f"{100*total_covered/total:.0f}" if total else "0"
    total_rev = sum(agg["region_revenue"].values())

    # Regional table rows
    rows_html = ""
    max_count = max(agg["region_counts"].values(), default=1)
    for region in REGION_ORDER:
        count   = agg["region_counts"].get(region, 0)
        if count == 0:
            continue
        covered = agg["region_covered"].get(region, 0)
        revenue = agg["region_revenue"].get(region, 0)
        share   = 100 * count / total if total else 0
        cov_pct = 100 * covered / count if count else 0
        avg_rev = revenue / count if count else 0
        bar_w   = int(80 * count / max_count)
        colour  = REGION_COLOURS.get(region, "#888")

        if cov_pct >= 80:
            pill = '<span class="pill pill-green">Good</span>'
        elif cov_pct >= 50:
            pill = '<span class="pill pill-yellow">Partial</span>'
        else:
            pill = '<span class="pill pill-red">At Risk</span>'

        rows_html += f"""
      <tr>
        <td><strong style="color:{colour}">{region}</strong></td>
        <td>
          <span class="bar-inline" style="width:{bar_w}px;background:{colour}"></span>
          {count}
        </td>
        <td>{share:.1f}%</td>
        <td>{covered}</td>
        <td>{cov_pct:.0f}%</td>
        <td>{_revenue_fmt(revenue)}</td>
        <td>{_revenue_fmt(avg_rev)}</td>
        <td>{pill}</td>
      </tr>"""

    # State breakdown table (top 15 states)
    state_rows = ""
    sorted_states = sorted(agg["state_counts"].items(), key=lambda x: -x[1])[:20]
    for state, cnt in sorted_states:
        region = STATE_TO_REGION.get(state, "Unknown")
        colour = REGION_COLOURS.get(region, "#888")
        state_rows += f"<tr><td>{state}</td><td style='color:{colour}'>{region}</td><td>{cnt}</td></tr>"

    state_table = f"""
<div class="table-card">
  <h2>Top States by Account Count</h2>
  <table>
    <thead><tr><th>State</th><th>Region</th><th>Accounts</th></tr></thead>
    <tbody>{state_rows}</tbody>
  </table>
</div>""" if state_rows else ""

    return HTML_TEMPLATE.format(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_accounts=total,
        regions_active=len([r for r in REGION_ORDER if agg["region_counts"].get(r, 0) > 0]),
        coverage_pct=coverage_pct,
        total_revenue=_revenue_fmt(total_rev),
        uncovered_count=uncovered,
        count_bar_img=_img_tag(charts.get("count_bar", "")),
        revenue_bar_img=_img_tag(charts.get("revenue_bar", "")),
        coverage_bar_img=_img_tag(charts.get("coverage_bar", "")),
        pie_img=_img_tag(charts.get("pie", "")),
        table_rows=rows_html,
        state_table=state_table,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a US regional account coverage report with visualisations."
    )
    parser.add_argument(
        "--source-report",
        metavar="REPORT_ID",
        default="00OVk00000KYxtNMAT",
        help="Salesforce report ID to source data from (default: 00OVk00000KYxtNMAT).",
    )
    parser.add_argument(
        "--soql-only",
        action="store_true",
        help="Skip the Analytics API and query directly via SOQL.",
    )
    parser.add_argument(
        "--output",
        default="./output/us_coverage_report.html",
        metavar="PATH",
        help="Output HTML file path (default: ./output/us_coverage_report.html).",
    )
    args = parser.parse_args()

    sf = get_salesforce_client()

    source = None if args.soql_only else args.source_report
    records = fetch_accounts(sf, source)

    if not records:
        logging.error("No records returned. Check your Salesforce connection and report ID.")
        sys.exit(1)

    agg    = aggregate(records)
    charts = make_charts(agg)

    # Console summary
    print(f"\n{'='*55}")
    print("US ACCOUNT COVERAGE SUMMARY")
    print(f"{'='*55}")
    print(f"  Total accounts : {agg['total']}")
    print(f"  No state data  : {agg['no_state']}")
    for region in REGION_ORDER:
        count   = agg["region_counts"].get(region, 0)
        covered = agg["region_covered"].get(region, 0)
        revenue = agg["region_revenue"].get(region, 0)
        if count:
            pct = f"{100*covered/count:.0f}%"
            print(f"  {region:<12} {count:>4} accounts  {pct:>4} covered  {_revenue_fmt(revenue):>10} ARR")
    print()

    html = build_html(agg, charts)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    logging.info("Report saved → %s", out_path.resolve())
    print(f"Open in browser: {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
