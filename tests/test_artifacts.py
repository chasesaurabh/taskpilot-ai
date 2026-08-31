from __future__ import annotations

from taskpilot.artifacts import LocalArtifactStore
from taskpilot.domain.models import ArtifactKind


def test_local_artifact_store_round_trips_immutable_content(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    created = store.put_text(
        run_id="11111111-1111-1111-1111-111111111111",
        kind=ArtifactKind.PATCH,
        content="diff --git a/app.py b/app.py\n",
        media_type="text/x-diff",
    )
    loaded, content = store.get_bytes(run_id=created.run_id, artifact_id=created.artifact_id)

    assert loaded == created
    assert content == b"diff --git a/app.py b/app.py\n"
    assert created.size_bytes == len(content)
