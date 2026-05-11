"""
Rules of Engagement — Slack interaction handler.

Receives POST callbacks from Slack when a sales pod leader clicks
DROP or KEEP on the stale accounts digest. Verifies the request,
updates Salesforce, then sends an ephemeral confirmation back to Slack.

Environment variables (all point to SSM SecureString paths):
  SLACK_SIGNING_SECRET_PARAM
  SF_INSTANCE_URL_PARAM
  SF_CLIENT_ID_PARAM
  SF_CLIENT_SECRET_PARAM
  SF_USERNAME_PARAM
  SF_PASSWORD_PARAM
  SF_SECURITY_TOKEN_PARAM
"""

import json
import os
import urllib.parse
import urllib.request

import boto3

from slack_verifier import verify_slack_signature
from salesforce import SalesforceClient

# Warm-start caches
_ssm = boto3.client("ssm")
_param_cache: dict[str, str] = {}
_sf_client: SalesforceClient | None = None

SALES_OPS_USER_ID = "0051p00000AtuwrAAB"


def _get_param(name: str) -> str:
    if name not in _param_cache:
        _param_cache[name] = _ssm.get_parameter(
            Name=name, WithDecryption=True
        )["Parameter"]["Value"]
    return _param_cache[name]


def _get_sf_client() -> SalesforceClient:
    global _sf_client
    if _sf_client is None:
        _sf_client = SalesforceClient(
            instance_url=_get_param(os.environ["SF_INSTANCE_URL_PARAM"]),
            client_id=_get_param(os.environ["SF_CLIENT_ID_PARAM"]),
            client_secret=_get_param(os.environ["SF_CLIENT_SECRET_PARAM"]),
            username=_get_param(os.environ["SF_USERNAME_PARAM"]),
            password=_get_param(os.environ["SF_PASSWORD_PARAM"]),
            security_token=_get_param(os.environ["SF_SECURITY_TOKEN_PARAM"]),
        )
    return _sf_client


def _post_to_slack(url: str, body: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5):
        pass


def lambda_handler(event: dict, context) -> dict:
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    raw_body = event.get("body", "")

    # Verify the request came from Slack
    signing_secret = _get_param(os.environ["SLACK_SIGNING_SECRET_PARAM"])
    if not verify_slack_signature(
        signing_secret=signing_secret,
        request_body=raw_body,
        timestamp=headers.get("x-slack-request-timestamp", ""),
        signature=headers.get("x-slack-signature", ""),
    ):
        return {"statusCode": 401, "body": "Invalid Slack signature"}

    # Slack sends interactions as URL-encoded `payload` field
    parsed = urllib.parse.parse_qs(raw_body)
    if "payload" not in parsed:
        return {"statusCode": 400, "body": "Missing payload"}

    payload = json.loads(parsed["payload"][0])

    action = payload["actions"][0]
    action_id = action["action_id"]      # "drop_account" | "keep_account"
    account_id = action["value"]         # 18-char Salesforce Account ID
    clicked_by = payload["user"]["name"]
    response_url = payload["response_url"]

    try:
        sf = _get_sf_client()

        if action_id == "drop_account":
            # Transfer ownership to Sales Operations
            sf.update_account(account_id, {"OwnerId": SALES_OPS_USER_ID})
            confirmation = (
                f":white_check_mark: *{clicked_by}* dropped account `{account_id}` "
                f"— ownership transferred to Sales Operations."
            )

        elif action_id == "keep_account":
            # Clear the stale flag so it won't appear next month
            sf.update_account(account_id, {"Stale_Account__c": False})
            confirmation = (
                f":handshake: *{clicked_by}* chose to keep account `{account_id}` "
                f"— no ownership change made."
            )

        else:
            return {"statusCode": 400, "body": f"Unknown action: {action_id}"}

    except Exception as exc:  # noqa: BLE001
        # Surface errors as ephemeral Slack messages so the user knows something went wrong
        _post_to_slack(
            response_url,
            {
                "response_type": "ephemeral",
                "replace_original": False,
                "text": f":x: Something went wrong — please retry or contact Sales Ops. (`{exc}`)",
            },
        )
        raise

    _post_to_slack(
        response_url,
        {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": confirmation,
        },
    )

    # Slack requires a 200 within 3 seconds — return empty body
    return {"statusCode": 200, "body": ""}
