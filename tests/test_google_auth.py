# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google login and its token (04-storage.md §3, D-062), with a fake Google: no network.

Every client id, secret and token here is fictional.
"""

import datetime as dt
import json
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import TransportError
from google.auth.transport import Request, Response
from google.oauth2.credentials import Credentials

from climblog import google_auth
from climblog.config import GoogleConfig
from climblog.google_auth import SCOPES, GoogleAuthError, NotLoggedIn

CLIENT = {
    "installed": {
        "client_id": "fictional-client.apps.googleusercontent.com",
        "client_secret": "fictional-client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}
ACCESS, REFRESH, NEW_ACCESS = "fictional-access-token", "fictional-refresh-token", "fictional-new"
SECRETS = (ACCESS, REFRESH, NEW_ACCESS, "fictional-client-secret")


def credentials(
    scopes: Sequence[str] = SCOPES,
    refresh_token: str | None = REFRESH,
    expiry: dt.datetime | None = None,
) -> Credentials:
    return Credentials(
        token=ACCESS,
        refresh_token=refresh_token,
        token_uri=CLIENT["installed"]["token_uri"],
        client_id=CLIENT["installed"]["client_id"],
        client_secret=CLIENT["installed"]["client_secret"],
        scopes=list(scopes),
        expiry=expiry or dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(hours=1),
    )


class FakeResponse(Response):
    def __init__(self, status: int, body: Mapping[str, Any]) -> None:
        self._status, self._data = status, json.dumps(body).encode()

    @property
    def status(self) -> int:
        return self._status

    @property
    def headers(self) -> dict[str, str]:
        return {"content-type": "application/json"}

    @property
    def data(self) -> bytes:
        return self._data


class FakeGoogle(Request):
    """Answers every request with `status` and `body`, or fails as if offline."""

    def __init__(
        self, status: int = 200, body: Mapping[str, Any] | None = None, offline: bool = False
    ) -> None:
        self.status, self.offline = status, offline
        self.body = body or {
            "access_token": NEW_ACCESS,
            "expires_in": 3600,
            "scope": " ".join(SCOPES),
        }
        self.calls: list[tuple[str, str, bytes | None]] = []

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        self.calls.append((url, method, body))
        if self.offline:
            raise TransportError("offline")
        return FakeResponse(self.status, self.body)


class FakeConsent:
    """The browser login: records what it was asked and grants `granted`."""

    def __init__(self, granted: Credentials | None = None) -> None:
        self.granted = granted or credentials()
        self.asked: list[tuple[Mapping[str, Any], Sequence[str], bool]] = []

    def __call__(
        self, client: Mapping[str, Any], scopes: Sequence[str], open_browser: bool
    ) -> Credentials:
        self.asked.append((client, scopes, open_browser))
        return self.granted


@pytest.fixture
def config(tmp_path: Path) -> GoogleConfig:
    secret = tmp_path / "client_secret.json"
    secret.write_text(json.dumps(CLIENT), encoding="utf-8")
    return GoogleConfig(client_secret=secret, token=tmp_path / "conf/climblog/google-token.json")


def logged_in(config: GoogleConfig, granted: Credentials | None = None) -> Path:
    return google_auth.login(config, consent=FakeConsent(granted))


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---- login ----


def test_login_saves_the_token_for_the_owner_only(config: GoogleConfig) -> None:
    consent = FakeConsent()
    path = google_auth.login(config, open_browser=False, consent=consent)
    assert path == config.token_file()
    assert consent.asked == [(CLIENT, SCOPES, False)]
    assert (mode(path), mode(path.parent)) == (0o600, 0o700)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (saved["refresh_token"], saved["scopes"]) == (REFRESH, list(SCOPES))
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temp file left


def test_login_again_replaces_the_token(config: GoogleConfig) -> None:
    logged_in(config)
    logged_in(config, credentials(refresh_token="fictional-second"))
    saved = json.loads(config.token_file().read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "fictional-second"


def test_login_needs_every_scope(config: GoogleConfig) -> None:
    with pytest.raises(GoogleAuthError, match=r"tick every box \(missing .*drive.file\)"):
        logged_in(config, credentials(scopes=SCOPES[:1]))
    with pytest.raises(GoogleAuthError, match="no refresh token"):
        logged_in(config, credentials(refresh_token=None))
    assert not config.token_file().exists()


def test_login_needs_a_desktop_client(config: GoogleConfig, tmp_path: Path) -> None:
    def fails(client: GoogleConfig, message: str) -> None:
        with pytest.raises(GoogleAuthError, match=message):
            logged_in(client)

    fails(GoogleConfig(), r"set \[google\] client_secret")
    fails(GoogleConfig(client_secret=tmp_path / "nowhere.json"), "client file not found")
    for name, text, message in [
        ("web.json", json.dumps({"web": CLIENT["installed"]}), "a web client; .*'Desktop app'"),
        ("list.json", "[]", "not a client; create"),
        ("bad.json", "{", "not a Google client file"),
    ]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        fails(GoogleConfig(client_secret=tmp_path / name), message)


def test_a_failed_save_keeps_the_old_token(
    config: GoogleConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = logged_in(config)
    before = path.read_bytes()

    def broken(self: Credentials, strip: object = None) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(Credentials, "to_json", broken)
    with pytest.raises(OSError, match="disk full"):
        logged_in(config)
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


# ---- the saved login ----


def test_a_valid_token_is_used_without_calling_google(config: GoogleConfig) -> None:
    logged_in(config)
    google = FakeGoogle()
    assert google_auth.load_credentials(config, request=google).token == ACCESS
    assert google.calls == []


def test_an_expired_token_is_refreshed_and_saved(config: GoogleConfig) -> None:
    logged_in(config, credentials(expiry=dt.datetime(2026, 10, 1)))
    google = FakeGoogle()
    assert google_auth.load_credentials(config, request=google).token == NEW_ACCESS
    assert [(url, method) for url, method, _ in google.calls] == [
        ("https://oauth2.googleapis.com/token", "POST")
    ]
    saved = json.loads(config.token_file().read_text(encoding="utf-8"))
    assert (saved["token"], saved["refresh_token"]) == (NEW_ACCESS, REFRESH)
    assert mode(config.token_file()) == 0o600


def test_refresh_can_be_forced(config: GoogleConfig) -> None:
    logged_in(config)
    google = FakeGoogle()
    assert google_auth.load_credentials(config, request=google, refresh=True).token == NEW_ACCESS
    assert len(google.calls) == 1


def test_a_refused_or_failed_refresh(config: GoogleConfig) -> None:
    logged_in(config)
    revoked = FakeGoogle(400, {"error": "invalid_grant", "error_description": "revoked"})
    with pytest.raises(GoogleAuthError, match=r"no longer accepts .* `climblog google login`"):
        google_auth.load_credentials(config, request=revoked, refresh=True)
    with pytest.raises(GoogleAuthError, match="cannot reach Google"):
        google_auth.load_credentials(config, request=FakeGoogle(offline=True), refresh=True)
    assert json.loads(config.token_file().read_text(encoding="utf-8"))["token"] == ACCESS


def test_no_saved_login(config: GoogleConfig) -> None:
    with pytest.raises(NotLoggedIn, match="not logged in to Google: run `climblog google login`"):
        google_auth.load_credentials(config, request=FakeGoogle())


def test_a_token_others_can_read_is_refused(config: GoogleConfig) -> None:
    path = logged_in(config)
    path.chmod(0o644)
    with pytest.raises(GoogleAuthError, match=r"can be read by others: run `chmod 600 .*`"):
        google_auth.load_credentials(config, request=FakeGoogle())


@pytest.mark.parametrize("text", ["{", "[]", '{"token": "x"}', '"text"'])
def test_a_broken_token_file(config: GoogleConfig, text: str) -> None:
    path = config.token_file()
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(GoogleAuthError, match="not a saved Google login"):
        google_auth.load_credentials(config, request=FakeGoogle())


def test_a_token_with_fewer_scopes_needs_a_new_login(config: GoogleConfig) -> None:
    path = logged_in(config)
    saved = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**saved, "scopes": list(SCOPES[:1])}), encoding="utf-8")
    with pytest.raises(GoogleAuthError, match="lacks permissions the app now needs"):
        google_auth.load_credentials(config, request=FakeGoogle())


# ---- logout ----


def test_logout_revokes_and_deletes(config: GoogleConfig) -> None:
    logged_in(config)
    google = FakeGoogle(200, {})
    assert google_auth.logout(config, request=google) is True
    assert google.calls == [
        ("https://oauth2.googleapis.com/revoke", "POST", f"token={REFRESH}".encode())
    ]
    assert not config.token_file().exists()


@pytest.mark.parametrize("google", [FakeGoogle(400, {}), FakeGoogle(offline=True)])
def test_logout_deletes_even_when_google_does_not_confirm(
    config: GoogleConfig, google: FakeGoogle
) -> None:
    logged_in(config)
    assert google_auth.logout(config, request=google) is False
    assert not config.token_file().exists()


def test_logout_deletes_a_broken_token_without_calling_google(config: GoogleConfig) -> None:
    path = config.token_file()
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    google = FakeGoogle()
    assert google_auth.logout(config, request=google) is False
    assert google.calls == []
    assert not path.exists()


def test_logout_without_a_login(config: GoogleConfig) -> None:
    assert google_auth.logout(config, request=FakeGoogle()) is None


def test_errors_never_hold_a_secret(config: GoogleConfig) -> None:
    logged_in(config)
    revoked = FakeGoogle(400, {"error": "invalid_grant", "error_description": REFRESH})
    with pytest.raises(GoogleAuthError) as error:
        google_auth.load_credentials(config, request=revoked, refresh=True)
    assert not any(secret in str(error.value) for secret in SECRETS)
