"""
Morning Pulse — Chief of Staff Briefing
Runs daily at 8:45 AM. Reads Gmail, Slack, and Google Calendar,
then sends a single priority-ranked DM to the executive.
"""

import os
import re
import datetime
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


# ── Config ─────────────────────────────────────────────────────────────────

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_USER_ID   = os.environ["SLACK_USER_ID"]        # e.g. "U0123ABCDEF"
MY_EMAIL        = os.environ["MY_EMAIL"]

CORE_CHANNELS = [
    "real_bps_only",
    "us-sales",
    "us-sales-pod-leaders",
    "insights-BPs",
    "team_new_york",
]

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Signals that mark an email as noise rather than signal
NOISE_PATTERNS = re.compile(
    r"unsubscribe|newsletter|no-reply|noreply|donotreply|"
    r"automated|notification|alert|digest|weekly|monthly|"
    r"your receipt|order confirmation|invoice|statement",
    re.IGNORECASE,
)

SIGNAL_PATTERNS = re.compile(
    r"announcement|org change|reorgani[sz]|policy update|policy change|"
    r"project update|roadmap|strategy|acquisition|merger|leadership|"
    r"headcount|reorg|all-hands|townhall|town hall|quarterly|OKR|"
    r"decision|approval|urgent|action required|FYI",
    re.IGNORECASE,
)

TZ = ZoneInfo("America/New_York")


# ── Google Auth ─────────────────────────────────────────────────────────────

def _google_creds() -> Credentials:
    token_path = os.path.join(os.path.dirname(__file__), "token.json")
    creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, GOOGLE_SCOPES)
            flow.redirect_uri = "http://localhost"
            auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
            print("\n" + "="*60)
            print("STEP 1: Open this URL in your browser:")
            print(f"\n{auth_url}\n")
            print("STEP 2: Sign in and click Allow.")
            print("STEP 3: Browser shows 'localhost refused to connect' — expected.")
            print("        Copy the ENTIRE URL from the address bar and paste below.")
            print("="*60 + "\n")
            redirect_url = input("Paste the full redirect URL here: ").strip()
            if redirect_url.startswith("4/") or ("code=" not in redirect_url):
                redirect_url = f"http://localhost/?code={redirect_url}&state=unused"
            flow.fetch_token(authorization_response=redirect_url)
            creds = flow.credentials
        with open(token_path, "w") as fh:
            fh.write(creds.to_json())

    return creds


# ── Step 1 — Gmail ──────────────────────────────────────────────────────────

def _extract_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_gmail_signals(creds: Credentials, since_ts: int) -> list[dict]:
    """Return relevant emails from the last 24 hours."""
    service = build("gmail", "v1", credentials=creds)

    query = f"in:inbox after:{since_ts}"
    results = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = results.get("messages", [])

    signals = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()

        headers  = detail["payload"]["headers"]
        sender   = _extract_header(headers, "From")
        subject  = _extract_header(headers, "Subject")
        snippet  = detail.get("snippet", "")

        if NOISE_PATTERNS.search(sender) or NOISE_PATTERNS.search(subject):
            continue

        if not (SIGNAL_PATTERNS.search(subject) or SIGNAL_PATTERNS.search(snippet)):
            continue

        signals.append({
            "sender":  sender,
            "subject": subject,
            "summary": snippet[:200],
        })

    return signals


# ── Step 2 — Slack ──────────────────────────────────────────────────────────

def fetch_slack_signals(client: WebClient, since_ts: float) -> dict:
    """
    Returns:
      mentions   — messages where the exec is @mentioned
      unreplied  — DMs with no reply from the exec in the last 24h
      requests   — messages in core channels that look like questions/requests
    """
    mentions:   list[str] = []
    unreplied:  list[str] = []
    requests:   list[str] = []

    oldest = str(since_ts)

    # (a) @mentions via search
    try:
        result = client.search_messages(query=f"<@{SLACK_USER_ID}>", count=20)
        for match in result["messages"]["matches"]:
            ts_float = float(match.get("ts", 0))
            if ts_float >= since_ts:
                channel_name = match.get("channel", {}).get("name", "?")
                text = match.get("text", "")[:200]
                mentions.append(f"#{channel_name}: {text}")
    except SlackApiError:
        pass

    # (b) Unreplied DMs
    try:
        convs = client.conversations_list(types="im", limit=50)
        for ch in convs["channels"]:
            history = client.conversations_history(channel=ch["id"], oldest=oldest, limit=20)
            thread_has_my_reply = False
            relevant_msg = None
            for msg in history["messages"]:
                if msg.get("user") != SLACK_USER_ID:
                    relevant_msg = msg.get("text", "")[:200]
                else:
                    thread_has_my_reply = True
            if relevant_msg and not thread_has_my_reply:
                user_info = client.users_info(user=ch["user"])
                name = user_info["user"]["profile"].get("real_name", ch["user"])
                unreplied.append(f"{name}: {relevant_msg}")
    except SlackApiError:
        pass

    # (c) Questions/requests in core channels
    question_re = re.compile(r"\?|can you|could you|please|would you|need you|thoughts on", re.IGNORECASE)
    try:
        all_channels = client.conversations_list(types="public_channel,private_channel", limit=200)
        channel_map  = {c["name"]: c["id"] for c in all_channels["channels"]}

        for ch_name in CORE_CHANNELS:
            ch_id = channel_map.get(ch_name)
            if not ch_id:
                continue
            history = client.conversations_history(channel=ch_id, oldest=oldest, limit=50)
            for msg in history["messages"]:
                text = msg.get("text", "")
                if SLACK_USER_ID in text or question_re.search(text):
                    requests.append(f"#{ch_name}: {text[:200]}")
    except SlackApiError:
        pass

    return {"mentions": mentions, "unreplied": unreplied, "requests": requests}


# ── Step 3 — Google Calendar cross-reference ────────────────────────────────

def fetch_calendar_flags(creds: Credentials, client: WebClient, since_ts: float) -> list[dict]:
    """
    For each meeting today, search Slack for recent threads about it.
    Flag meetings where pivot / blocker / decision language appears.
    """
    service = build("calendar", "v3", credentials=creds)

    now   = datetime.datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()

    change_re = re.compile(
        r"pivot|scope change|blocker|blocked|decision|cancelled|rescheduled|"
        r"pushing back|delay|new direction|concern|risk|issue",
        re.IGNORECASE,
    )

    flagged = []
    oldest  = str(since_ts)

    for event in events_result.get("items", []):
        title = event.get("summary", "Untitled")
        start_time = event["start"].get("dateTime", event["start"].get("date", ""))

        search_terms = [title]
        for attendee in event.get("attendees", [])[:4]:
            email = attendee.get("email", "")
            name  = email.split("@")[0].replace(".", " ")
            search_terms.append(name)

        slack_hits = []
        for term in search_terms:
            try:
                result = client.search_messages(query=term, count=10)
                for match in result["messages"]["matches"]:
                    if float(match.get("ts", 0)) >= since_ts:
                        text = match.get("text", "")
                        if change_re.search(text):
                            slack_hits.append(text[:200])
            except SlackApiError:
                pass

        if slack_hits:
            flagged.append({
                "meeting": title,
                "start":   start_time,
                "signals": slack_hits[:3],
            })

    return flagged


# ── Step 4 — Compose & Send ─────────────────────────────────────────────────

def _priority_bullet(prefix: str, items: list[str]) -> str:
    lines = "\n".join(f"  • {item}" for item in items)
    return f"*{prefix}*\n{lines}"


def compose_message(
    today: datetime.date,
    gmail_signals: list[dict],
    slack_signals: dict,
    calendar_flags: list[dict],
) -> str:
    sections: list[tuple[int, str]] = []  # (priority, text)

    # P1 — action required today
    p1_items: list[str] = []

    for msg in slack_signals["unreplied"]:
        p1_items.append(f"[Slack DM — no reply] {msg}")

    for flag in calendar_flags:
        for sig in flag["signals"]:
            p1_items.append(f"[{flag['meeting']} @ {flag['start'][:16]}] {sig}")

    if p1_items:
        sections.append((1, _priority_bullet(":red_circle: P1 — Action Required Today", p1_items)))

    # P2 — pre-meeting context
    p2_items: list[str] = []

    for req in slack_signals["requests"][:5]:
        p2_items.append(req)

    for mention in slack_signals["mentions"][:5]:
        p2_items.append(f"[Mention] {mention}")

    if p2_items:
        sections.append((2, _priority_bullet(":large_yellow_circle: P2 — Pre-Meeting Context", p2_items)))

    # P3 — awareness
    p3_items: list[str] = []

    for email in gmail_signals:
        p3_items.append(f"[Email from {email['sender']}] {email['subject']} — {email['summary']}")

    if p3_items:
        sections.append((3, _priority_bullet(":white_circle: P3 — Awareness (No Action Needed)", p3_items)))

    if not sections:
        return ""

    body = "\n\n".join(text for _, text in sorted(sections))
    date_str = today.strftime("%A, %B %-d")
    return f"Good morning — here's your pulse for {date_str}.\n\n{body}"


def send_slack_dm(client: WebClient, message: str) -> None:
    dm = client.conversations_open(users=[SLACK_USER_ID])
    channel_id = dm["channel"]["id"]
    client.chat_postMessage(channel=channel_id, text=message, mrkdwn=True)


# ── Entrypoint ──────────────────────────────────────────────────────────────

def run() -> None:
    now      = datetime.datetime.now(TZ)
    since_dt = now - datetime.timedelta(hours=24)
    since_ts = since_dt.timestamp()
    since_unix_date = int(since_dt.strftime("%s"))

    creds  = _google_creds()
    client = WebClient(token=SLACK_BOT_TOKEN)

    gmail_signals   = fetch_gmail_signals(creds, since_unix_date)
    slack_signals   = fetch_slack_signals(client, since_ts)
    calendar_flags  = fetch_calendar_flags(creds, client, since_ts)

    message = compose_message(now.date(), gmail_signals, slack_signals, calendar_flags)

    if message:
        send_slack_dm(client, message)
        print("Morning pulse sent.")
    else:
        print("Nothing to report — no DM sent.")


if __name__ == "__main__":
    run()
