"""
Quick smoke test for Google API connectivity.
Run: python test_google.py
"""

import datetime
from zoneinfo import ZoneInfo
from morning_pulse import _google_creds
from googleapiclient.discovery import build

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
