"""Promotion must preserve serving data on invalid transitions; uses real local Qdrant."""

import pytest
from app.services.qdrant_client import switch_aliases
from qdrant_client import QdrantClient, models


@pytest.fixture
def qdrant():
    client = QdrantClient(location=":memory:")
    yield client
    client.close()


def collection(client, name, version):
    client.create_collection(
        name, vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
    )
    client.upsert(
        name, points=[models.PointStruct(id=1, vector=[1.0], payload={"version": version})]
    )


def test_missing_target_preserves_the_existing_alias(qdrant):
    collection(qdrant, "games-v1", "v1")
    switch_aliases({"games": "games-v1"}, client=qdrant)
    with pytest.raises(ValueError):
        switch_aliases({"games": "missing-candidate"}, client=qdrant)
    assert qdrant.retrieve("games", [1])[0].payload == {"version": "v1"}


def test_alias_name_collision_never_deletes_a_serving_collection(qdrant):
    collection(qdrant, "games", "v1")
    collection(qdrant, "games-v2", "v2")
    with pytest.raises(ValueError):
        switch_aliases({"games": "games-v2"}, client=qdrant)
    assert qdrant.collection_exists("games")
    assert qdrant.retrieve("games", [1])[0].payload == {"version": "v1"}


def test_valid_promotion_moves_all_aliases_and_preserves_rollback_collections(qdrant):
    for name in ("games", "reports"):
        collection(qdrant, f"{name}-v1", "v1")
        collection(qdrant, f"{name}-v2", "v2")
    switch_aliases({name: f"{name}-v1" for name in ("games", "reports")}, client=qdrant)
    switch_aliases({name: f"{name}-v2" for name in ("games", "reports")}, client=qdrant)
    for name in ("games", "reports"):
        assert qdrant.retrieve(name, [1])[0].payload == {"version": "v2"}
        assert qdrant.retrieve(f"{name}-v1", [1])[0].payload == {"version": "v1"}
