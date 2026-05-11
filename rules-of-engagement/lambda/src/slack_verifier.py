import hashlib
import hmac
import time


def verify_slack_signature(
    signing_secret: str,
    request_body: str,
    timestamp: str,
    signature: str,
) -> bool:
    """
    Verify a Slack request using the v0 HMAC-SHA256 signing scheme.
    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not timestamp or not signature:
        return False

    # Reject requests older than 5 minutes to prevent replay attacks
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False

    sig_basestring = f"v0:{timestamp}:{request_body}"
    computed = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(computed, signature)
