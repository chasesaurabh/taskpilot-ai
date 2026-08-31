"""Durable artifact storage for full patches and validation logs."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from taskpilot.domain.models import ArtifactKind, ArtifactRef


class ArtifactNotFoundError(RuntimeError):
    """The requested artifact does not exist in the configured store."""


class ArtifactStore(Protocol):
    def put_text(
        self,
        *,
        run_id: str,
        kind: ArtifactKind,
        content: str,
        media_type: str,
    ) -> ArtifactRef: ...

    def get_bytes(self, *, run_id: str, artifact_id: str) -> tuple[ArtifactRef, bytes]: ...


class LocalArtifactStore:
    """Filesystem-backed object store with immutable content and metadata objects."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put_text(
        self,
        *,
        run_id: str,
        kind: ArtifactKind,
        content: str,
        media_type: str,
    ) -> ArtifactRef:
        encoded = content.encode("utf-8")
        artifact_id = str(uuid4())
        ref = ArtifactRef(
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            media_type=media_type,
            size_bytes=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
        directory = self._run_directory(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{artifact_id}.blob").write_bytes(encoded)
        (directory / f"{artifact_id}.json").write_text(ref.model_dump_json(), encoding="utf-8")
        return ref

    def get_bytes(self, *, run_id: str, artifact_id: str) -> tuple[ArtifactRef, bytes]:
        directory = self._run_directory(run_id)
        metadata = directory / f"{artifact_id}.json"
        blob = directory / f"{artifact_id}.blob"
        if not metadata.is_file() or not blob.is_file():
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        ref = ArtifactRef.model_validate_json(metadata.read_text(encoding="utf-8"))
        content = blob.read_bytes()
        if hashlib.sha256(content).hexdigest() != ref.sha256:
            raise RuntimeError(f"Artifact integrity check failed: {artifact_id}")
        return ref, content

    def _run_directory(self, run_id: str) -> Path:
        if not run_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in run_id.lower()
        ):
            raise ValueError("Run IDs used for artifacts must be UUID-like")
        return self._root / run_id


class S3ArtifactStore:
    """S3-compatible object-store adapter loaded only with the artifacts extra."""

    def __init__(self, *, bucket: str, prefix: str = "taskpilot", **client_options: Any) -> None:
        try:
            boto3 = importlib.import_module("boto3")
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install taskpilot-ai[artifacts] for S3 artifact storage") from exc
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = boto3.client("s3", **client_options)

    def put_text(
        self,
        *,
        run_id: str,
        kind: ArtifactKind,
        content: str,
        media_type: str,
    ) -> ArtifactRef:
        encoded = content.encode("utf-8")
        artifact_id = str(uuid4())
        ref = ArtifactRef(
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            media_type=media_type,
            size_bytes=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
            created_at=datetime.now(UTC),
        )
        key = self._key(run_id, artifact_id)
        self._client.put_object(
            Bucket=self._bucket,
            Key=f"{key}.blob",
            Body=encoded,
            ContentType=media_type,
            Metadata={"sha256": ref.sha256},
        )
        self._client.put_object(
            Bucket=self._bucket,
            Key=f"{key}.json",
            Body=ref.model_dump_json().encode(),
            ContentType="application/json",
        )
        return ref

    def get_bytes(self, *, run_id: str, artifact_id: str) -> tuple[ArtifactRef, bytes]:
        key = self._key(run_id, artifact_id)
        try:
            metadata_object = self._client.get_object(Bucket=self._bucket, Key=f"{key}.json")
            blob_object = self._client.get_object(Bucket=self._bucket, Key=f"{key}.blob")
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}") from exc
            raise
        metadata = json.loads(metadata_object["Body"].read())
        ref = ArtifactRef.model_validate(metadata)
        content = blob_object["Body"].read()
        if hashlib.sha256(content).hexdigest() != ref.sha256:
            raise RuntimeError(f"Artifact integrity check failed: {artifact_id}")
        return ref, content

    def _key(self, run_id: str, artifact_id: str) -> str:
        return f"{self._prefix}/{run_id}/{artifact_id}"
