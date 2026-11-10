"""Personal access keys: sending entries from an iPhone Shortcut or Siri, and nothing else."""

from contextlib import nullcontext
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.keys import MAX_KEYS
from app.auth.models import AccessKey
from app.captures.models import Capture
from app.db.session import get_session_factory
from app.main import app
from tests import factories as f
from tests.conftest import register

SHORTCUT_URL = "/v1/captures?background=true"


@pytest.fixture
def sessions(db):
    app.dependency_overrides[get_session_factory] = lambda: lambda: nullcontext(db)
    yield
    app.dependency_overrides.pop(get_session_factory, None)


def new_key(client, auth, name: str = "iPhone Shortcut") -> dict:
    response = client.post("/v1/me/keys", json={"name": name}, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def shortcut(client, key: str, content: str, input_type: str = "VOICE"):
    """Exactly what the Shortcut in the setup steps sends."""
    return client.post(
        SHORTCUT_URL,
        json={"content": content, "input_type": input_type},
        headers={"Authorization": f"Bearer {key}"},
    )


def studied_ai():
    return f.output(
        events=[f.event("STUDY", "AI study", "Studied AI", time=f.when(duration_minutes=60))]
    )


class TestManagingKeys:
    def test_a_key_is_shown_once_and_only_its_hash_is_stored(self, client, auth, db):
        created = new_key(client, auth)
        assert created["key"].startswith("pos_key_") and len(created["key"]) > 40
        assert created["hint"] == created["key"][-4:]
        listed = client.get("/v1/me/keys", headers=auth).json()
        assert [k["name"] for k in listed] == ["iPhone Shortcut"]
        assert "key" not in listed[0] and listed[0]["last_used_at"] is None
        stored = db.scalar(select(AccessKey))
        assert created["key"] not in (stored.key_hash, stored.hint, stored.name)

    def test_names_are_required_and_trimmed(self, client, auth):
        assert new_key(client, auth, "  Siri  ")["name"] == "Siri"
        blank = client.post("/v1/me/keys", json={"name": "  "}, headers=auth)
        assert blank.status_code == 422
        assert client.post("/v1/me/keys", json={}, headers=auth).json()["name"] == "iPhone Shortcut"

    def test_a_revoked_key_stops_working_at_once(self, client, auth, fake_ai, sessions):
        created = new_key(client, auth)
        assert client.delete(f"/v1/me/keys/{created['id']}", headers=auth).status_code == 204
        assert client.get("/v1/me/keys", headers=auth).json() == []
        refused = shortcut(client, created["key"], "Studied AI")
        assert refused.status_code == 401 and refused.json()["error"]["code"] == "INVALID_KEY"
        again = client.delete(f"/v1/me/keys/{created['id']}", headers=auth)
        assert again.status_code == 404

    def test_nobody_else_can_see_or_revoke_your_keys(self, client, auth):
        created = new_key(client, auth)
        other = {"Authorization": f"Bearer {register(client, 'other@example.com')['access_token']}"}
        assert client.get("/v1/me/keys", headers=other).json() == []
        assert client.delete(f"/v1/me/keys/{created['id']}", headers=other).status_code == 404
        assert len(client.get("/v1/me/keys", headers=auth).json()) == 1

    def test_there_is_a_limit_on_keys(self, client, auth):
        for n in range(MAX_KEYS):
            new_key(client, auth, f"Key {n}")
        too_many = client.post("/v1/me/keys", json={"name": "One more"}, headers=auth)
        assert too_many.status_code == 409 and too_many.json()["error"]["code"] == "TOO_MANY_KEYS"
        first = client.get("/v1/me/keys", headers=auth).json()[0]
        client.delete(f"/v1/me/keys/{first['id']}", headers=auth)
        new_key(client, auth, "Now it fits")

    def test_keys_go_with_the_account(self, client, auth, db):
        new_key(client, auth)
        response = client.request(
            "DELETE", "/v1/me", json={"password": "correct horse battery"}, headers=auth
        )
        assert response.status_code == 204
        assert db.scalar(select(AccessKey)) is None

    def test_a_key_cannot_manage_keys(self, client, auth):
        key = {"Authorization": f"Bearer {new_key(client, auth)['key']}"}
        assert client.get("/v1/me/keys", headers=key).status_code == 403
        assert client.post("/v1/me/keys", json={"name": "x"}, headers=key).status_code == 403


class TestSendingFromAShortcut:
    def test_dictated_words_are_saved_at_once_and_understood(
        self, client, auth, fake_ai, db, sessions, clock
    ):
        fake_ai.respond("Studied", studied_ai())
        created = new_key(client, auth)
        response = shortcut(client, created["key"], "Studied AI for an hour")
        assert response.status_code == 202
        assert response.json()["message"] == "Saved. Understanding it…"  # what Siri says
        capture = db.scalar(select(Capture))
        assert capture.input_type == "VOICE" and capture.transcript == "Studied AI for an hour"
        timeline = client.get("/v1/timeline", headers=auth).json()["items"]
        assert [e["title"] for e in timeline] == ["AI study"]
        listed = client.get("/v1/me/keys", headers=auth).json()[0]
        assert listed["last_used_at"] is not None

    def test_typed_text_and_lowercase_types_work_too(self, client, auth, fake_ai, db, sessions):
        fake_ai.respond("Studied", studied_ai())
        key = new_key(client, auth)["key"]
        assert shortcut(client, key, "Studied AI", input_type="text").status_code == 202
        assert db.scalar(select(Capture.input_type)) == "TEXT"

    def test_without_waiting_the_reply_says_what_was_understood(self, client, auth, fake_ai):
        fake_ai.respond("Studied", studied_ai())
        key = new_key(client, auth)["key"]
        response = client.post(
            "/v1/captures",
            json={"content": "Studied AI"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        assert [e["title"] for e in response.json()["events_created"]] == ["AI study"]

    def test_a_key_sends_entries_and_does_nothing_else(self, client, auth):
        key = {"Authorization": f"Bearer {new_key(client, auth)['key']}"}
        for method, path in (
            ("GET", "/v1/me"),
            ("GET", "/v1/timeline"),
            ("GET", "/v1/captures"),
            ("GET", "/v1/me/export"),
            ("PATCH", "/v1/me"),
            ("POST", "/v1/auth/logout"),
        ):
            response = client.request(method, path, json={}, headers=key)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["error"]["code"] == "KEY_NOT_ALLOWED"

    def test_made_up_and_malformed_keys_are_refused(self, client, auth):
        new_key(client, auth)
        made_up = shortcut(client, "pos_key_" + "x" * 43, "Studied AI")
        assert made_up.status_code == 401 and made_up.json()["error"]["code"] == "INVALID_KEY"
        no_scheme = client.post(
            SHORTCUT_URL, json={"content": "Studied AI"}, headers={"Authorization": "pos_key_x"}
        )
        assert no_scheme.status_code == 401
        assert no_scheme.json()["error"]["code"] == "NOT_AUTHENTICATED"

    def test_the_app_session_still_sends_entries(self, client, auth, fake_ai):
        fake_ai.respond("Studied", studied_ai())
        response = client.post("/v1/captures", json={"content": "Studied AI"}, headers=auth)
        assert response.status_code == 200

    def test_last_used_shows_when_a_key_was_last_used(self, client, auth, fake_ai, clock):
        fake_ai.respond("Studied", studied_ai())
        key = new_key(client, auth)["key"]
        shortcut(client, key, "Studied AI")
        clock.moment += timedelta(minutes=30)
        shortcut(client, key, "Studied AI again")
        listed = client.get("/v1/me/keys", headers=auth).json()[0]
        assert datetime.fromisoformat(listed["last_used_at"]) == clock.now()
