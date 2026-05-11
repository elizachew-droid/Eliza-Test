"""
Minimal Salesforce REST API client using only the Python standard library.
Authenticates via OAuth 2.0 Username-Password flow (Connected App required).
"""

import json
import urllib.error
import urllib.parse
import urllib.request


class SalesforceError(Exception):
    pass


class SalesforceClient:
    API_VERSION = "v59.0"

    def __init__(
        self,
        instance_url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        security_token: str,
    ) -> None:
        self.instance_url, self.access_token = self._authenticate(
            instance_url, client_id, client_secret, username, password, security_token
        )

    def _authenticate(
        self,
        instance_url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        security_token: str,
    ) -> tuple[str, str]:
        data = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
                "username": username,
                # Salesforce requires password + security token concatenated
                "password": password + security_token,
            }
        ).encode()

        req = urllib.request.Request(
            f"{instance_url}/services/oauth2/token",
            data=data,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            raise SalesforceError(f"OAuth failed ({exc.code}): {body}") from exc

        return result["instance_url"], result["access_token"]

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        url = f"{self.instance_url}/services/data/{self.API_VERSION}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            raise SalesforceError(
                f"Salesforce API {method} {path} failed ({exc.code}): {body}"
            ) from exc

    def update_account(self, account_id: str, fields: dict) -> None:
        """PATCH a Salesforce Account record with the given field values."""
        self._request("PATCH", f"/sobjects/Account/{account_id}", fields)

    def get_account(self, account_id: str, fields: list[str]) -> dict:
        """GET specific fields from a Salesforce Account record."""
        field_list = ",".join(fields)
        return self._request("GET", f"/sobjects/Account/{account_id}?fields={field_list}")
