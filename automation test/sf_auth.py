"""
sf_auth.py
----------
Shared Salesforce authentication helper.

Supports two auth modes — whichever variables are present in .env are used:

MODE A — Session Token (required for SSO orgs like Checkout.com)
  SF_ACCESS_TOKEN   your session ID / OAuth access token
  SF_INSTANCE_URL   your org's base URL (e.g. https://checkout.lightning.force.com)

MODE B — Username / Password (non-SSO orgs only)
  SF_USERNAME
  SF_PASSWORD
  SF_SECURITY_TOKEN
  SF_INSTANCE_URL

How to get SF_ACCESS_TOKEN for an SSO org
------------------------------------------
Option 1 — Browser session (quickest, expires in ~2hrs):
  1. Log in to Salesforce in Chrome/Firefox
  2. Open DevTools > Application tab > Cookies
  3. Find the cookie named 'sid' for your Salesforce domain
  4. Copy its value into SF_ACCESS_TOKEN in your .env

Option 2 — OAuth2 Connected App (persistent, recommended for automation):
  1. Salesforce Setup > App Manager > New Connected App
  2. Enable OAuth, add scopes: api, refresh_token
  3. Copy Consumer Key → SF_CLIENT_ID, Consumer Secret → SF_CLIENT_SECRET
  4. Run: python get_oauth_token.py   (generates and saves your token)

Option 3 — Salesforce CLI (if you have sf/sfdx installed):
  sf org display --target-org <alias> --json
  Copy the 'accessToken' value into SF_ACCESS_TOKEN
"""

import logging
import os
import sys
from urllib.parse import urlparse


def _clean_instance_url(raw: str) -> str:
    """
    Strip any path/query from the instance URL so simple_salesforce
    gets just the base origin (e.g. https://checkout.lightning.force.com).
    """
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    return f"{parsed.scheme}://{parsed.netloc}"


def get_salesforce_client():
    """
    Return an authenticated simple_salesforce Salesforce instance.
    Tries Session Token auth first; falls back to Username/Password.
    """
    try:
        from simple_salesforce import Salesforce, SalesforceAuthenticationFailed
    except ImportError:
        logging.error("simple_salesforce not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    raw_url = os.getenv("SF_INSTANCE_URL", "")
    instance_url = _clean_instance_url(raw_url)
    access_token = os.getenv("SF_ACCESS_TOKEN", "")
    api_version = os.getenv("SF_API_VERSION", "59.0")

    # ------------------------------------------------------------------
    # MODE A: Session / Access Token (works with SSO orgs)
    # ------------------------------------------------------------------
    if access_token:
        if not instance_url:
            logging.error("SF_ACCESS_TOKEN is set but SF_INSTANCE_URL is missing.")
            sys.exit(1)
        try:
            logging.info("Authenticating via access token to %s …", instance_url)
            sf = Salesforce(
                instance_url=instance_url,
                session_id=access_token,
                version=api_version,
            )
            # Probe the API to confirm the token is valid
            sf.query("SELECT Id FROM User LIMIT 1")
            logging.info("Session token authentication: OK")
            return sf
        except Exception as exc:
            logging.error(
                "Session token authentication failed: %s\n"
                "Your SF_ACCESS_TOKEN may have expired (browser tokens last ~2 hrs).\n"
                "See sf_auth.py for instructions on refreshing it.",
                exc,
            )
            sys.exit(1)

    # ------------------------------------------------------------------
    # MODE B: Username / Password (non-SSO orgs only)
    # ------------------------------------------------------------------
    username = os.getenv("SF_USERNAME", "")
    password = os.getenv("SF_PASSWORD", "")
    security_token = os.getenv("SF_SECURITY_TOKEN", "")
    client_id = os.getenv("SF_CLIENT_ID", "")
    client_secret = os.getenv("SF_CLIENT_SECRET", "")

    missing = [k for k, v in {"SF_USERNAME": username, "SF_PASSWORD": password, "SF_INSTANCE_URL": instance_url}.items() if not v]
    if missing:
        logging.error(
            "No SF_ACCESS_TOKEN found and username/password auth is incomplete.\n"
            "Missing: %s\n\n"
            "For SSO orgs (Checkout.com): set SF_ACCESS_TOKEN in your .env\n"
            "See sf_auth.py for how to obtain it.",
            ", ".join(missing),
        )
        sys.exit(1)

    domain = "test" if "test.salesforce" in instance_url.lower() or "sandbox" in instance_url.lower() else "login"

    try:
        logging.info("Authenticating via username/password to %s …", instance_url)
        sf = Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            consumer_key=client_id or None,
            consumer_secret=client_secret or None,
            domain=domain,
            version=api_version,
        )
        logging.info("Username/password authentication: OK")
        return sf
    except SalesforceAuthenticationFailed as exc:
        msg = str(exc)
        if "INVALID_SSO_GATEWAY_URL" in msg or "SSO" in msg.upper():
            logging.error(
                "Your org uses SSO — username/password auth is blocked.\n"
                "Set SF_ACCESS_TOKEN in your .env instead.\n"
                "See sf_auth.py for three ways to obtain the token."
            )
        else:
            logging.error("Salesforce authentication failed: %s", exc)
        sys.exit(1)
