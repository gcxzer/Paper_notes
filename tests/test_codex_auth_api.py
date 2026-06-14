from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ui.backend.codex_auth_api import (
    _cancel_all_attempts,
    get_codex_auth_status,
    logout_codex_auth,
    poll_codex_auth,
    start_codex_auth,
)


@dataclass
class FakeLoginResult:
    success: bool
    error: str = ""


@dataclass
class FakePlan:
    value: str


@dataclass
class FakeAccountRoot:
    type: str = "chatgpt"
    email: str = "user@example.test"
    plan_type: FakePlan = field(default_factory=lambda: FakePlan("plus"))


@dataclass
class FakeAccount:
    root: FakeAccountRoot


@dataclass
class FakeAccountResponse:
    account: FakeAccount | None
    requires_openai_auth: bool


class FakeDeviceHandle:
    login_id = "login-123"
    user_code = "ABCD-EFGH"
    verification_url = "https://auth.example.test/device"

    def __init__(self, state) -> None:
        self.state = state
        self.ready = threading.Event()
        self.result = FakeLoginResult(success=True)
        self.cancelled = False

    def wait(self) -> FakeLoginResult:
        self.ready.wait(timeout=2)
        if self.cancelled:
            return FakeLoginResult(success=False, error="cancelled")
        self.state["logged_in"] = self.result.success
        return self.result

    def cancel(self) -> None:
        self.cancelled = True
        self.ready.set()


class FakeCodex:
    def __init__(self, state) -> None:
        self.state = state
        self.handle = FakeDeviceHandle(state)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def login_chatgpt_device_code(self) -> FakeDeviceHandle:
        self.state["handles"].append(self.handle)
        return self.handle

    def account(self, *, refresh_token: bool = False):
        self.state["refresh_requested"] = refresh_token
        if not self.state["logged_in"]:
            return FakeAccountResponse(account=None, requires_openai_auth=True)
        return FakeAccountResponse(
            account=FakeAccount(FakeAccountRoot()),
            requires_openai_auth=bool(self.state.get("requires_openai_auth", False)),
        )

    def logout(self) -> None:
        self.state["logged_in"] = False

    def close(self) -> None:
        self.closed = True


def fake_codex_factory(state):
    return lambda: FakeCodex(state)


def test_codex_auth_status_maps_current_codex_account():
    state = {"logged_in": True, "handles": []}

    payload = get_codex_auth_status(codex_factory=fake_codex_factory(state))

    assert payload["loggedIn"] is True
    assert payload["authMode"] == "chatgpt"
    assert payload["accountEmail"] == "user@example.test"
    assert payload["planType"] == "plus"


def test_codex_auth_status_treats_returned_account_as_signed_in_even_if_openai_auth_required():
    state = {"logged_in": True, "handles": [], "requires_openai_auth": True}

    payload = get_codex_auth_status(codex_factory=fake_codex_factory(state))

    assert payload["loggedIn"] is True
    assert payload["accountEmail"] == "user@example.test"


def test_codex_auth_start_poll_and_connect():
    state = {"logged_in": False, "handles": []}
    factory = fake_codex_factory(state)
    try:
        started = start_codex_auth(codex_factory=factory)
        handle = state["handles"][0]

        assert started == {
            "status": "started",
            "userCode": "ABCD-EFGH",
            "deviceAuthId": "login-123",
            "verificationUri": "https://auth.example.test/device",
            "interval": 3,
        }
        assert poll_codex_auth({"deviceAuthId": "login-123", "userCode": "ABCD-EFGH"}, codex_factory=factory) == {
            "status": "pending"
        }

        handle.ready.set()
        connected = _poll_until_connected(factory)

        assert connected["status"] == "connected"
        assert connected["auth"]["loggedIn"] is True
        assert connected["auth"]["accountEmail"] == "user@example.test"
    finally:
        _cancel_all_attempts()


def test_codex_auth_logout_clears_current_codex_account():
    state = {"logged_in": True, "handles": []}

    payload = logout_codex_auth(codex_factory=fake_codex_factory(state))

    assert payload["loggedIn"] is False
    assert state["logged_in"] is False


def test_codex_auth_poll_rejects_unknown_attempt():
    try:
        poll_codex_auth({"deviceAuthId": "missing", "userCode": "ABCD-EFGH"})
    except ValueError as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("expected missing attempt to raise")


def _poll_until_connected(factory):
    deadline = time.time() + 2
    while time.time() < deadline:
        payload = poll_codex_auth({"deviceAuthId": "login-123", "userCode": "ABCD-EFGH"}, codex_factory=factory)
        if payload["status"] == "connected":
            return payload
        time.sleep(0.01)
    raise AssertionError("Codex login did not complete")
