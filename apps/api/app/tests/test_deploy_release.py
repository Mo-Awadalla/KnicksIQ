"""Synthetic rollback behavior only; no real Render, database, or Qdrant writes."""

from copy import deepcopy
from typing import Any

import pytest
from app.services import deploy_release
from app.services.deploy_release import deploy


class DeploymentSimulation:
    """Stateful fake services make assertions cover identity, not just calls."""

    def __init__(self, monkeypatch):
        self.record: dict[str, Any] = {
            "tested_commit": "a" * 40,
            "services": {
                "api": {"id": "api", "url": "https://api.example"},
                "web": {"id": "web", "url": "https://web.example"},
            },
            "rollback": {
                "api_deployment": "old-api",
                "web_deployment": "old-web",
                "data_version": "v1",
                "qdrant_aliases": {"games": "games-v1", "reports": "reports-v1"},
            },
            "candidate": {
                "data_version": "v2",
                "aliases": {"games": "games-v2", "reports": "reports-v2"},
            },
            "deployments": {},
        }
        self.old_commits = {"api": "b" * 40, "web": "c" * 40}
        self.commits = self.old_commits.copy()
        self.data = "v1"
        self.alias_mapping = self.record["rollback"]["qdrant_aliases"].copy()
        self.events: list[tuple] = []
        self.calls: list[tuple[str, dict | None]] = []
        self.saved: list[dict] = []
        self.promotion_failure: str | None = None
        self.restore_failures: set[str] = set()
        self.restore_mismatches: set[str] = set()
        self.pending: dict[str, list] = {"api": [], "web": []}
        self.cancel_failure: str | None = None
        self.fail_smoke = True
        monkeypatch.setattr(deploy_release, "activate", self.activate)
        monkeypatch.setattr(deploy_release, "dataset_version", self.dataset_version)
        monkeypatch.setattr(deploy_release, "switch_aliases", self.switch_aliases)
        monkeypatch.setattr(deploy_release, "aliases", self.aliases)
        monkeypatch.setattr(deploy_release.urllib.request, "urlopen", self.forbid_network)

    @staticmethod
    def forbid_network(*_args, **_kwargs):
        pytest.fail("Synthetic rollback tests must never access a real network service")

    def save(self, record):
        self.saved.append(deepcopy(record))
        self.events.append(("save", record["rollout"]["status"]))

    def request(self, path, payload):
        self.calls.append((path, deepcopy(payload)))
        component = path.split("/")[1]
        if path.endswith("/deploys/old-" + component):
            self.events.append(("capture", component))
            return {"id": "old-" + component, "commit": {"id": self.old_commits[component]}}
        if "?limit=" in path:
            self.events.append(("list_pending", component))
            if self.cancel_failure == component:
                raise TimeoutError("Unable to determine pending deployments")
            return self.pending[component]
        if path.endswith("/cancel"):
            self.events.append(("cancel", component, path.split("/")[-2]))
            return {}
        if path.endswith("/rollback"):
            self.events.append(("restore", component))
            assert payload == {"deployId": "old-" + component}
            if component in self.restore_failures:
                raise RuntimeError("Restoration unavailable")
            if component not in self.restore_mismatches:
                self.commits[component] = self.old_commits[component]
            return {"id": "rollback-" + component}
        assert path == f"services/{component}/deploys"
        assert payload == {"commitId": self.record["tested_commit"]}
        self.events.append(("promote", component))
        self.commits[component] = self.record["tested_commit"]
        if self.promotion_failure == component:
            raise TimeoutError("Uncertain network outcome after mutation")
        return {"id": "new-" + component}

    def wait(self, component, deployment):
        self.events.append(("wait", component, deployment))
        return {"id": deployment, "commit": {"id": self.commits[component]}}

    async def activate(self, version):
        restoring = version == self.record["rollback"]["data_version"]
        self.events.append(("restore" if restoring else "promote", "data"))
        if restoring and "data" in self.restore_failures:
            raise RuntimeError("Dataset restoration unavailable")
        if not (restoring and "data" in self.restore_mismatches):
            self.data = version
        if not restoring and self.promotion_failure == "data":
            raise TimeoutError("Dataset committed before connection dropped")

    async def dataset_version(self):
        self.events.append(("verify", "data"))
        return self.data

    def switch_aliases(self, mapping):
        restoring = mapping == self.record["rollback"]["qdrant_aliases"]
        self.events.append(("restore" if restoring else "promote", "aliases"))
        if restoring and "aliases" in self.restore_failures:
            raise RuntimeError("Alias restoration unavailable")
        if not (restoring and "aliases" in self.restore_mismatches):
            self.alias_mapping = mapping.copy()
        if not restoring and self.promotion_failure == "aliases":
            raise TimeoutError("Aliases switched before connection dropped")

    def aliases(self):
        self.events.append(("verify", "aliases"))
        return self.alias_mapping.copy()

    def smoke(self, api, web, version):
        self.events.append(("smoke", api, web, version))
        expected = self.record.get("candidate", {}).get("data_version") or "v1"
        assert (api, web, version) == ("https://api.example", "https://web.example", expected)
        if self.fail_smoke:
            raise RuntimeError("Post-promotion smoke failed")

    def run(self, request=None, wait=None):
        deploy(
            self.record,
            self.save,
            request=request or self.request,
            wait=wait or self.wait,
            smoke_check=self.smoke,
        )

    @property
    def restored_components(self):
        return [event[1] for event in self.events if event[0] == "restore"]


@pytest.fixture
def simulation(monkeypatch):
    return DeploymentSimulation(monkeypatch)


def test_failed_second_service_restores_both_attempted_services(simulation):
    simulation.promotion_failure = "web"
    with pytest.raises(RuntimeError, match="Promotion stopped") as caught:
        simulation.run()
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert simulation.restored_components == ["web", "api"]
    assert simulation.commits == simulation.old_commits
    assert simulation.record["rollout"]["status"] == "restored"


def test_restoration_failure_does_not_skip_other_services(simulation):
    simulation.restore_failures.add("web")
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.commits["api"] == simulation.old_commits["api"]
    assert simulation.record["rollout"]["status"] == "restoration_failed"
    assert simulation.record["rollout"]["restoration_failures"] == [
        {"component": "web", "error_type": "RuntimeError"}
    ]


def test_post_promotion_failure_restores_exact_coordinated_state(simulation):
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.events[:2] == [("capture", "api"), ("capture", "web")]
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.commits == simulation.old_commits
    assert simulation.data == simulation.record["rollback"]["data_version"]
    assert simulation.alias_mapping == simulation.record["rollback"]["qdrant_aliases"]
    assert simulation.record["rollout"]["rollback_commits"] == simulation.old_commits
    assert simulation.record["rollout"]["restored_deployments"] == {
        component: {"id": "rollback-" + component, "commit": simulation.old_commits[component]}
        for component in ("web", "api")
    }
    assert simulation.record["rollout"]["restoration_failures"] == []
    assert simulation.saved[-1]["rollout"]["status"] == "restored"
    assert ("verify", "aliases") in simulation.events
    assert ("verify", "data") in simulation.events
    for index, event in enumerate(simulation.events):
        if event[0] == "promote":
            assert simulation.events[index - 1] == ("save", "starting")
    assert any(event[0] == "smoke" for event in simulation.events)


@pytest.mark.parametrize(
    ("component", "restored"),
    [("aliases", ["aliases", "data", "web", "api"]), ("data", ["data", "web", "api"])],
)
def test_uncertain_promotion_restores_every_attempted_component(simulation, component, restored):
    simulation.promotion_failure = component
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == restored
    assert simulation.commits == simulation.old_commits
    assert simulation.data == "v1"
    assert simulation.alias_mapping == simulation.record["rollback"]["qdrant_aliases"]
    assert simulation.record["rollout"]["status"] == "restored"
    assert simulation.record["rollout"]["failure_type"] == "TimeoutError"
    assert not any(event[0] == "smoke" for event in simulation.events)


def test_multiple_restoration_failures_still_attempt_all_remaining_components(simulation):
    simulation.restore_failures.update({"aliases", "data", "web"})
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.commits["api"] == simulation.old_commits["api"]
    assert simulation.record["rollout"]["status"] == "restoration_failed"
    assert simulation.record["rollout"]["restoration_failures"] == [
        {"component": component, "error_type": "RuntimeError"}
        for component in ("aliases", "data", "web")
    ]


@pytest.mark.parametrize("component", ["aliases", "data", "web", "api"])
def test_successful_restoration_response_with_wrong_identity_fails_closed(simulation, component):
    simulation.restore_mismatches.add(component)
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.record["rollout"]["status"] == "restoration_failed"
    assert simulation.record["rollout"]["restoration_failures"] == [
        {"component": component, "error_type": "RuntimeError"}
    ]


def test_wrong_restored_deployment_id_cannot_prove_service_restoration(simulation):
    def wait(component, deployment):
        result = simulation.wait(component, deployment)
        if deployment == "rollback-web":
            result["id"] = "different-deployment"
        return result

    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run(wait=wait)
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.record["rollout"]["status"] == "restoration_failed"
    assert simulation.record["rollout"]["restoration_failures"] == [
        {"component": "web", "error_type": "RuntimeError"}
    ]


@pytest.mark.parametrize(
    "captured",
    [
        None,
        {},
        {"id": "old-web"},
        {"id": "old-web", "commit": None},
        {"id": "old-web", "commit": {"id": "short-sha"}},
        {"id": "old-web", "commit": {"id": 7}},
        {"id": "other-deployment", "commit": {"id": "c" * 40}},
    ],
)
def test_missing_captured_identity_blocks_all_promotion_writes(simulation, captured):
    def request(path, payload):
        if path == "services/web/deploys/old-web":
            return captured
        return simulation.request(path, payload)

    with pytest.raises(RuntimeError, match="captured deployment id and full commit.id"):
        simulation.run(request=request)
    assert simulation.commits == simulation.old_commits
    assert simulation.data == "v1"
    assert simulation.saved == []
    assert all(payload is None for _, payload in simulation.calls)
    assert "rollout" not in simulation.record


def test_unavailable_captured_deployment_blocks_all_promotion_writes(simulation):
    def request(path, payload):
        if path == "services/web/deploys/old-web":
            raise TimeoutError("Captured deployment could not be read")
        return simulation.request(path, payload)

    with pytest.raises(TimeoutError, match="Captured deployment could not be read"):
        simulation.run(request=request)
    assert simulation.commits == simulation.old_commits
    assert simulation.saved == []
    assert all(payload is None for _, payload in simulation.calls)


@pytest.mark.parametrize("unchanged", [False, True])
def test_unchanged_data_and_aliases_are_not_mutated_during_restoration(simulation, unchanged):
    simulation.record["candidate"] = (
        {
            "data_version": "v1",
            "aliases": simulation.record["rollback"]["qdrant_aliases"].copy(),
        }
        if unchanged
        else {}
    )
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == ["web", "api"]
    assert ("promote", "data") not in simulation.events
    assert ("promote", "aliases") not in simulation.events
    assert simulation.record["rollout"]["status"] == "restored"


def test_promoted_commit_mismatch_stops_before_data_or_alias_mutation(simulation):
    def wait(component, deployment):
        result = simulation.wait(component, deployment)
        if deployment == "new-web":
            result["commit"] = {"id": "d" * 40}
        return result

    with pytest.raises(RuntimeError, match="Promotion stopped") as caught:
        simulation.run(wait=wait)
    assert str(caught.value.__cause__) == "Render deployed a different commit"
    assert simulation.restored_components == ["web", "api"]
    assert simulation.data == "v1"
    assert simulation.record["rollout"]["status"] == "restored"


def test_candidate_alias_set_change_is_rejected_and_previous_state_restored(simulation):
    simulation.record["candidate"]["aliases"]["extra"] = "extra-v2"
    with pytest.raises(RuntimeError, match="Promotion stopped") as caught:
        simulation.run()
    assert str(caught.value.__cause__) == "Candidate aliases differ from rollback alias set"
    assert ("promote", "aliases") not in simulation.events
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.alias_mapping == simulation.record["rollback"]["qdrant_aliases"]
    assert simulation.record["rollout"]["status"] == "restored"


def test_inflight_candidate_deployments_cancelled_before_service_restoration(simulation):
    statuses = [
        "created",
        "build_in_progress",
        "pre_deploy_in_progress",
        "update_in_progress",
        "queued",
    ]
    simulation.pending["web"] = [
        {"deploy": {"id": status, "status": status, "commit": {"id": "a" * 40}}}
        for status in statuses
    ] + [
        {"deploy": {"id": "live", "status": "live", "commit": {"id": "a" * 40}}},
        {"deploy": {"id": "unrelated", "status": "queued", "commit": {"id": "b" * 40}}},
    ]
    simulation.promotion_failure = "web"
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert [event[2] for event in simulation.events if event[0] == "cancel"] == statuses
    restore_index = simulation.events.index(("restore", "web"))
    assert all(
        index < restore_index
        for index, event in enumerate(simulation.events)
        if event[0] == "cancel"
    )
    assert simulation.record["rollout"]["status"] == "restored"


def test_cancellation_uncertainty_does_not_skip_service_restoration(simulation):
    simulation.cancel_failure = "web"
    with pytest.raises(RuntimeError, match="Promotion stopped"):
        simulation.run()
    assert simulation.restored_components == ["aliases", "data", "web", "api"]
    assert simulation.commits == simulation.old_commits
    assert simulation.record["rollout"]["status"] == "restoration_failed"
    assert simulation.record["rollout"]["restoration_failures"] == [
        {"component": "web", "stage": "cancel_pending", "error_type": "TimeoutError"}
    ]


def test_successful_promotion_does_not_invoke_restoration(simulation):
    simulation.fail_smoke = False
    simulation.run()
    assert simulation.record["rollout"]["status"] == "live"
    assert simulation.restored_components == []
    assert simulation.commits == {"api": "a" * 40, "web": "a" * 40}
    assert simulation.data == "v2"
    assert simulation.alias_mapping == simulation.record["candidate"]["aliases"]
