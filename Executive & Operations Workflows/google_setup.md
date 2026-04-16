# Google OAuth Setup

## One-time steps

1. Go to https://console.cloud.google.com/
2. Create a new project (or reuse an existing one).
3. Enable the **Gmail API** and **Google Calendar API** for the project.
4. Under *APIs & Services → Credentials*, create an **OAuth 2.0 Client ID**
   (Application type: *Desktop app*).
5. Download the JSON file and save it as `credentials.json` in this folder.
6. Run the workflow once manually so the browser-based consent screen fires:
   ```
   python morning_pulse.py
   ```
   A `token.json` will be created automatically after you approve access.
   Subsequent runs use the saved token (auto-refreshed).

## Scopes requested
- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/calendar.readonly`

Both are read-only — the workflow never modifies your Gmail or Calendar.

## Files to keep out of version control
Add these to your `.gitignore`:
```
credentials.json
token.json
.env
```
