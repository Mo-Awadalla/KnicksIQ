import pytest
from app.services.deploy_release import deploy


def test_failed_second_service_restores_both_attempted_services():
    record = {
        "tested_commit": "a" * 40,
        "services": {
            "api": {"id": "api", "url": "https://api.example"},
            "web": {"id": "web", "url": "https://web.example"},
        },
        "rollback": {
            "api_deployment": "old-api",
            "web_deployment": "old-web",
            "data_version": "v1",
            "qdrant_aliases": {"games": "games-v1"},
        },
        "deployments": {},
    }
    calls = []

    def request(path, payload):
        calls.append((path, payload))
        if "?limit=" in path:
            return []
        if path == "services/web/deploys":
            raise RuntimeError("Uncertain network outcome")
        return {"id": "new-api" if path.endswith("/deploys") else "rollback"}

    with pytest.raises(RuntimeError, match="Promotion stopped"):
        deploy(
            record,
            lambda _: None,
            request=request,
            wait=lambda *_: {"commit": {"id": "a" * 40}},
            smoke_check=lambda *_: None,
        )
    assert [path for path, _ in calls if path.endswith("/rollback")] == [
        "services/web/rollback",
        "services/api/rollback",
    ]
    assert record["rollout"]["status"] == "restored"


def test_restoration_failure_does_not_skip_other_services():
    record = {
        "tested_commit": "a" * 40,
        "services": {
            "api": {"id": "api", "url": "https://api.example"},
            "web": {"id": "web", "url": "https://web.example"},
        },
        "rollback": {
            "api_deployment": "old-api",
            "web_deployment": "old-web",
            "data_version": "v1",
            "qdrant_aliases": {"games": "v1"},
        },
        "deployments": {},
    }
    restored = []

    def request(path, payload):
        if "?limit=" in path:
            return []
        if path.endswith("/rollback"):
            restored.append(path)
            if "/web/" in path:
                raise RuntimeError("Restoration unavailable")
        return {"id": "deployment"}

    def fail_smoke(*_):
        raise RuntimeError("Smoke failed")

    with pytest.raises(RuntimeError, match="Promotion stopped"):
        deploy(
            record,
            lambda _: None,
            request=request,
            wait=lambda *_: {"commit": {"id": "a" * 40}},
            smoke_check=fail_smoke,
        )
    assert restored == ["services/web/rollback", "services/api/rollback"]
    assert record["rollout"]["status"] == "restoration_failed"
