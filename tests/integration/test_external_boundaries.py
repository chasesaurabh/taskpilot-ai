from __future__ import annotations

import importlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from taskpilot.artifacts import S3ArtifactStore
from taskpilot.domain.models import ArtifactKind
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy

S3_ENDPOINT = os.getenv("TASKPILOT_TEST_S3_ENDPOINT_URL")
CONTAINER_IMAGE = os.getenv("TASKPILOT_TEST_CONTAINER_IMAGE")


@pytest.mark.s3
@pytest.mark.skipif(S3_ENDPOINT is None, reason="S3-compatible test endpoint is not configured")
def test_s3_artifact_store_round_trip() -> None:
    assert S3_ENDPOINT is not None
    bucket = f"taskpilot-test-{uuid4()}"
    boto3 = importlib.import_module("boto3")
    client = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    store = S3ArtifactStore(
        bucket=bucket,
        prefix="integration",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
    )
    try:
        created = store.put_text(
            run_id=str(uuid4()),
            kind=ArtifactKind.VALIDATION_LOG,
            content="full validation output",
            media_type="text/plain",
        )
        loaded, content = store.get_bytes(run_id=created.run_id, artifact_id=created.artifact_id)
        assert loaded == created
        assert content == b"full validation output"
    finally:
        objects = client.list_objects_v2(Bucket=bucket).get("Contents", [])
        if objects:
            client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": item["Key"]} for item in objects]},
            )
        client.delete_bucket(Bucket=bucket)


@pytest.mark.container
@pytest.mark.skipif(CONTAINER_IMAGE is None, reason="Container test image is not configured")
def test_validation_executes_in_an_ephemeral_container(tmp_path: Path) -> None:
    assert CONTAINER_IMAGE is not None
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "value.txt").write_text("isolated\n", encoding="utf-8")
    workspace = RepositoryWorkspace(
        repository,
        RepositoryToolPolicy(
            allowed_roots=(tmp_path,),
            allow_commands=True,
            allowed_commands=(("python", "-c"),),
            execution_backend="container",
            container_image=CONTAINER_IMAGE,
            command_timeout_seconds=60,
        ),
    )

    result = workspace.execute(
        ("python", "-c", "from pathlib import Path; print(Path('value.txt').read_text())")
    )

    assert result.exit_code == 0
    output_lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert output_lines[-1] == "isolated"
