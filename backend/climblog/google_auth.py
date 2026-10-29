# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google login (04-storage.md §3, D-011, D-062): an OAuth desktop client, a local token.

`climblog google login` asks Google, in the browser, for access to Sheets and to the Drive files
the app creates; the token is saved in the config folder, readable by the owner only, and is
never printed or logged. The Google backend gets its credentials from `load_credentials`, which
refreshes the access token when it has expired. The network is reached through `consent` (the
browser login) and `request` (token refresh, revoke), so the tests never call Google.
"""

import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport import Request
from google.auth.transport.requests import Request as HttpRequest
from google.oauth2.credentials import Credentials

from climblog.config import GoogleConfig

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",  # only the files the app creates
)
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
LOGIN = "run `climblog google login`"

# The browser login: the client config, the scopes and whether to open a browser → credentials.
Consent = Callable[[Mapping[str, Any], Sequence[str], bool], Credentials]


class GoogleAuthError(Exception):
    """The Google login can't be used; the message says what to do. Never holds a token."""


class NotLoggedIn(GoogleAuthError):
    pass


def browser_consent(
    client: Mapping[str, Any], scopes: Sequence[str], open_browser: bool
) -> Credentials:  # pragma: no cover - opens a browser and talks to Google
    """Google's consent page in the browser, answered on a loopback port (installed-app flow)."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2.rfc6749.errors import OAuth2Error

    flow = InstalledAppFlow.from_client_config(dict(client), list(scopes))
    try:
        credentials: Credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=open_browser,
            access_type="offline",  # a refresh token, so the login lasts
            prompt="consent",  # a refresh token every time, not only the first
        )
    except OAuth2Error as error:
        raise GoogleAuthError(f"Google refused the login: {error.error}") from None
    except Warning:  # oauthlib raises it when fewer scopes were granted than asked
        raise GoogleAuthError(
            "not every permission was granted: log in again and tick every box"
        ) from None
    return credentials


def login(
    config: GoogleConfig, *, open_browser: bool = True, consent: Consent | None = None
) -> Path:
    """Ask Google for access and save the token. Returns where it was saved."""
    client = read_client(config)
    credentials = (consent or browser_consent)(client, SCOPES, open_browser)
    missing = set(SCOPES) - set(credentials.granted_scopes or credentials.scopes or ())
    if missing:
        raise GoogleAuthError(
            "not every permission was granted: log in again and tick every box "
            f"(missing {', '.join(sorted(missing))})"
        )
    if not credentials.refresh_token:
        raise GoogleAuthError("Google sent no refresh token: log in again")
    path = config.token_file()
    save_token(path, credentials)
    return path


def read_client(config: GoogleConfig) -> dict[str, Any]:
    """The OAuth client file named in the config: a "Desktop app" client."""
    if config.client_secret is None:
        raise GoogleAuthError(
            'no Google client: set [google] client_secret = "…" in the app config '
            "(README, Google Sheets)"
        )
    path = config.client_secret
    try:
        client = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GoogleAuthError(f"{path}: Google client file not found") from None
    except (OSError, UnicodeDecodeError, ValueError):
        raise GoogleAuthError(f"{path}: not a Google client file (JSON)") from None
    if not isinstance(client, dict) or "installed" not in client:
        kind = "a web client" if isinstance(client, dict) and "web" in client else "not a client"
        raise GoogleAuthError(
            f"{path}: {kind}; create an OAuth client of type 'Desktop app' and download its JSON"
        )
    return client


def save_token(path: Path, credentials: Credentials) -> None:
    """Write the token atomically, readable by the owner only, in a folder only the owner opens."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(credentials.to_json())
            file.write("\n")
        os.replace(temp, path)  # mkstemp made it 0600
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def load_credentials(
    config: GoogleConfig, *, request: Request | None = None, refresh: bool = False
) -> Credentials:
    """The saved login, its access token refreshed (and saved) when it has expired, or always
    with `refresh` (to check that Google still accepts it)."""
    path = config.token_file()
    credentials = _read_token(path)
    if refresh or not credentials.valid:
        try:
            credentials.refresh(request or HttpRequest())
        except RefreshError:
            raise GoogleAuthError(
                f"Google no longer accepts the saved login (revoked or expired): {LOGIN}"
            ) from None
        except TransportError:
            raise GoogleAuthError("cannot reach Google to refresh the login") from None
        save_token(path, credentials)
    return credentials


def _read_token(path: Path) -> Credentials:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        raise NotLoggedIn(f"not logged in to Google: {LOGIN}") from None
    if mode & 0o077:
        raise GoogleAuthError(f"{path} can be read by others: run `chmod 600 {path}`")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        credentials: Credentials = Credentials.from_authorized_user_info(info)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
        raise GoogleAuthError(f"{path}: not a saved Google login: {LOGIN}") from None
    if not set(SCOPES) <= set(credentials.scopes or ()):
        raise GoogleAuthError(f"the saved login lacks permissions the app now needs: {LOGIN}")
    return credentials


def logout(config: GoogleConfig, *, request: Request | None = None) -> bool | None:
    """Ask Google to revoke the login, then delete the token whatever Google answers.

    Returns whether Google confirmed, or None when there was no saved login.
    """
    path = config.token_file()
    if not path.exists():
        return None
    try:
        token = json.loads(path.read_text(encoding="utf-8")).get("refresh_token")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        token = None
    revoked = False
    if isinstance(token, str):
        try:
            response = (request or HttpRequest())(
                REVOKE_URI,
                method="POST",
                body=urlencode({"token": token}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            revoked = response.status == 200
        except TransportError:
            revoked = False
    path.unlink(missing_ok=True)
    return revoked
