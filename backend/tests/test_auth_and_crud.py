from datetime import timedelta

from app.clock import FixedClock
from tests.conftest import NOW, register


def headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestAuth:
    def test_register_login_refresh_logout(self, client):
        tokens = register(client)
        assert tokens["user"]["timezone"] == "Africa/Casablanca"
        assert client.get("/v1/me", headers=headers(tokens)).status_code == 200

        login = client.post(
            "/v1/auth/login", json={"email": "ME@example.com", "password": "correct horse battery"}
        )
        assert login.status_code == 200

        refreshed = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200
        # The old tokens stop working after rotation.
        assert client.get("/v1/me", headers=headers(tokens)).status_code == 401
        assert (
            client.post(
                "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            ).status_code
            == 401
        )

        new = refreshed.json()
        assert client.post("/v1/auth/logout", headers=headers(new)).status_code == 204
        assert client.get("/v1/me", headers=headers(new)).status_code == 401

    def test_errors_use_one_format(self, client):
        register(client)
        duplicate = client.post(
            "/v1/auth/register",
            json={"email": "me@example.com", "password": "another long password"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "EMAIL_TAKEN"
        bad = client.post(
            "/v1/auth/login", json={"email": "me@example.com", "password": "wrong password!"}
        )
        assert bad.json()["error"]["code"] == "INVALID_CREDENTIALS"
        invalid = client.post("/v1/auth/register", json={"email": "nope", "password": "short"})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_FAILED"

    def test_access_token_expires(self, client, clock):
        tokens = register(client)
        clock.moment = NOW + timedelta(hours=2)
        response = client.get("/v1/me", headers=headers(tokens))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_EXPIRED"

    def test_profile_update_validates(self, client, auth):
        assert (
            client.patch("/v1/me", json={"timezone": "Mars/Base"}, headers=auth).status_code == 422
        )
        ok = client.patch(
            "/v1/me", json={"timezone": "Europe/Paris", "default_currency": None}, headers=auth
        )
        assert ok.json()["timezone"] == "Europe/Paris" and ok.json()["default_currency"] is None

    def test_starter_areas_exist(self, client, auth):
        names = [a["name"] for a in client.get("/v1/areas", headers=auth).json()]
        assert names == ["Career", "Education", "Finance", "Health", "Personal"]


class TestIsolation:
    def test_users_cannot_see_each_others_data(self, client):
        alice = headers(register(client, "alice@example.com"))
        bob = headers(register(client, "bob@example.com"))
        project = client.post("/v1/projects", json={"name": "Secret"}, headers=alice).json()
        event = client.post(
            "/v1/events", json={"event_type": "STUDY", "title": "Private study"}, headers=alice
        ).json()
        assert client.get(f"/v1/projects/{project['id']}", headers=bob).status_code == 404
        assert client.get(f"/v1/events/{event['id']}", headers=bob).status_code == 404
        assert (
            client.patch(f"/v1/events/{event['id']}", json={"title": "x"}, headers=bob).status_code
            == 404
        )
        assert client.get("/v1/timeline", headers=bob).json()["items"] == []
        # Linking to someone else's project is refused as if it didn't exist.
        own = client.post(
            "/v1/events",
            json={"event_type": "STUDY", "title": "Mine", "project_ids": [project["id"]]},
            headers=bob,
        )
        assert own.status_code == 404


class TestProjects:
    def test_aliases_and_name_uniqueness(self, client, auth):
        created = client.post(
            "/v1/projects", json={"name": "TenderPilot", "aliases": ["tender app"]}, headers=auth
        )
        assert created.status_code == 201 and created.json()["aliases"] == ["tender app"]
        clash = client.post("/v1/projects", json={"name": "Tender Pilot"}, headers=auth)
        assert clash.status_code == 409 and clash.json()["error"]["code"] == "PROJECT_NAME_TAKEN"
        other = client.post("/v1/projects", json={"name": "BLANI"}, headers=auth).json()
        taken = client.post(
            f"/v1/projects/{other['id']}/aliases", json={"alias": "Tender App"}, headers=auth
        )
        assert taken.status_code == 409 and taken.json()["error"]["code"] == "ALIAS_TAKEN"

    def test_deleting_frees_the_name(self, client, auth):
        project = client.post("/v1/projects", json={"name": "Old"}, headers=auth).json()
        assert client.delete(f"/v1/projects/{project['id']}", headers=auth).status_code == 204
        assert client.post("/v1/projects", json={"name": "Old"}, headers=auth).status_code == 201

    def test_detail_reports_time_invested(self, client, auth):
        project = client.post("/v1/projects", json={"name": "TenderPilot"}, headers=auth).json()
        for minutes in (60, 90):
            client.post(
                "/v1/events",
                json={
                    "event_type": "PROJECT_WORK",
                    "title": "Work",
                    "duration_minutes": minutes,
                    "project_ids": [project["id"]],
                },
                headers=auth,
            )
        detail = client.get(f"/v1/projects/{project['id']}", headers=auth).json()
        assert detail["stats"]["total_seconds"] == 150 * 60
        assert detail["stats"]["total_display"] == "2h 30m"
        assert len(detail["recent_events"]) == 2


class TestOtherEntities:
    def test_goal_evidence_includes_project_work(self, client, auth):
        goal = client.post(
            "/v1/goals", json={"title": "Become an AI engineer"}, headers=auth
        ).json()
        project = client.post(
            "/v1/projects", json={"name": "TenderPilot", "goal_ids": [goal["id"]]}, headers=auth
        ).json()
        client.post(
            "/v1/events",
            json={
                "event_type": "PROJECT_WORK",
                "title": "Work",
                "duration_minutes": 120,
                "project_ids": [project["id"]],
            },
            headers=auth,
        )
        detail = client.get(f"/v1/goals/{goal['id']}", headers=auth).json()
        assert detail["projects"][0]["name"] == "TenderPilot"
        assert detail["last_7_days"] == [
            {"event_type": "PROJECT_WORK", "seconds": 7200, "display": "2h", "events": 1}
        ]

    def test_tasks_complete_and_reopen(self, client, auth):
        task = client.post("/v1/tasks", json={"title": "Finish backend"}, headers=auth).json()
        done = client.patch(
            f"/v1/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=auth
        ).json()
        assert done["completed_at"] is not None
        reopened = client.patch(
            f"/v1/tasks/{task['id']}", json={"status": "TODO"}, headers=auth
        ).json()
        assert reopened["completed_at"] is None

    def test_habit_names_are_unique_while_active(self, client, auth):
        client.post("/v1/habits", json={"name": "Exercise", "target_count": 3}, headers=auth)
        assert client.post("/v1/habits", json={"name": "exercise"}, headers=auth).status_code == 409

    def test_knowledge_aliases_resolve(self, client, auth):
        created = client.post(
            "/v1/knowledge",
            json={"title": "Retrieval-Augmented Generation", "aliases": ["RAG"]},
            headers=auth,
        )
        assert created.status_code == 201
        assert client.post("/v1/knowledge", json={"title": "rag"}, headers=auth).status_code == 409
        found = client.get("/v1/knowledge", params={"q": "RAG"}, headers=auth).json()
        assert [k["title"] for k in found] == ["Retrieval-Augmented Generation"]


class TestAccountData:
    def test_export_and_delete(self, client, auth):
        client.post("/v1/events", json={"event_type": "STUDY", "title": "Study"}, headers=auth)
        export = client.get("/v1/me/export", headers=auth).json()
        assert export["format"] == "personal-os-export"
        assert len(export["events"]) == 1
        assert "password_hash" not in export["user"]
        wrong = client.request(
            "DELETE", "/v1/me", json={"password": "nope nope nope"}, headers=auth
        )
        assert wrong.status_code == 401
        gone = client.request(
            "DELETE", "/v1/me", json={"password": "correct horse battery"}, headers=auth
        )
        assert gone.status_code == 204
        assert client.get("/v1/me", headers=auth).status_code == 401


def test_fixed_clock_helper():
    assert FixedClock(NOW).now() == NOW
