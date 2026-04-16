"""
Quick smoke test for Google API connectivity.
Run: python test_google.py
"""

import os
import datetime
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


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
            print("STEP 3: Your browser will show 'localhost refused to connect'.")
            print("        That is EXPECTED. Look at the address bar — the URL")
            print("        will look like:  http://localhost/?code=4/0AXXX...&state=...")
            print("STEP 4: Copy that ENTIRE URL from the address bar and paste below.")
            print("="*60 + "\n")
            redirect_url = input("Paste the full redirect URL here: ").strip()
            if redirect_url.startswith("4/") or ("code=" not in redirect_url):
                redirect_url = f"http://localhost/?code={redirect_url}&state=unused"
            flow.fetch_token(authorization_response=redirect_url)
            creds = flow.credentials
        with open(token_path, "w") as fh:
            fh.write(creds.to_json())

    return creds

TZ = ZoneInfo("America/New_York")


def test_gmail():
    print("\n--- Gmail ---")
    creds = _google_creds()
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"  Connected as: {profile['emailAddress']}")
    print(f"  Total messages: {profile['messagesTotal']}")

    results = service.users().messages().list(userId="me", q="in:inbox", maxResults=3).execute()
    messages = results.get("messages", [])
    print(f"  Recent inbox messages (up to 3):")
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        print(f"    From: {headers.get('From', '?')}")
        print(f"    Subject: {headers.get('Subject', '?')}")
        print()
    print("  Gmail: OK")


def test_calendar():
    print("\n--- Google Calendar ---")
    creds = _google_creds()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=5,
    ).execute()

    events = events_result.get("items", [])
    if events:
        print(f"  Today's meetings ({len(events)}):")
        for e in events:
            title = e.get("summary", "Untitled")
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            print(f"    {start_time[:16]}  {title}")
    else:
        print("  No meetings found for today.")
    print("  Calendar: OK")


if __name__ == "__main__":
    try:
        test_gmail()
        test_calendar()
        print("\nAll Google APIs connected successfully.")
    except Exception as e:
        print(f"\nError: {e}")
