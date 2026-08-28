"""Credible no-key model for the bundled pagination demonstration."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from taskpilot.domain.models import (
    AnalysisReport,
    FailureDiagnosis,
    FinalReport,
    Finding,
    ImplementationPlan,
    ImplementationProposal,
    PlanStep,
    ProposedFileChange,
    ReviewResult,
    RunStatus,
    Severity,
    TaskAnalysis,
)
from taskpilot.models.demo import DeterministicModel

PAGINATED_APP = '''"""Small FastAPI application used by the TaskPilot demonstration."""

from fastapi import FastAPI, Query

app = FastAPI(title="TaskPilot Sample API")

PRODUCTS = [
    {"id": 1, "name": "Keyboard"},
    {"id": 2, "name": "Mouse"},
    {"id": 3, "name": "Monitor"},
    {"id": 4, "name": "Dock"},
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products")
def list_products(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    return {
        "items": PRODUCTS[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "total": len(PRODUCTS),
    }
'''

PAGINATED_TESTS = """from fastapi.testclient import TestClient

from sample_api.app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_products_are_paginated() -> None:
    response = client.get("/products", params={"offset": 1, "limit": 2})
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"id": 2, "name": "Mouse"},
            {"id": 3, "name": "Monitor"},
        ],
        "offset": 1,
        "limit": 2,
        "total": 4,
    }


def test_product_pagination_rejects_invalid_limits() -> None:
    assert client.get("/products", params={"limit": 0}).status_code == 422
    assert client.get("/products", params={"limit": 101}).status_code == 422
"""


def pagination_demo_model() -> DeterministicModel:
    """Return deterministic structured outputs for the documented sample task."""

    def analyze(prompt: str) -> TaskAnalysis:
        lowered = prompt.lower()
        if "pagination" not in lowered or "product" not in lowered:
            raise ValueError(
                "Demo mode supports only the documented product-pagination task; "
                "configure a model provider for general requests"
            )
        return TaskAnalysis(
            objective="Add bounded pagination to GET /products and update its tests",
            acceptance_criteria=(
                "offset is non-negative",
                "limit is between 1 and 100",
                "the response includes items and pagination metadata",
                "tests pass",
            ),
            constraints=("Preserve the health endpoint",),
            risk_level="low",
        )

    def proposal(prompt: str) -> ImplementationProposal:
        return ImplementationProposal(
            summary="Add bounded offset/limit pagination and coverage",
            changes=(
                ProposedFileChange(
                    path="sample_api/app.py",
                    operation="replace",
                    content=PAGINATED_APP,
                    expected_sha256=_context_hash(prompt, "sample_api/app.py"),
                    rationale=(
                        "Expose bounded pagination metadata without changing product records."
                    ),
                ),
                ProposedFileChange(
                    path="tests/test_app.py",
                    operation="replace",
                    content=PAGINATED_TESTS,
                    expected_sha256=_context_hash(prompt, "tests/test_app.py"),
                    rationale="Verify slices, metadata, health behavior, and invalid limits.",
                ),
            ),
        )

    command = (Path(sys.executable).name, "-m", "pytest", "-q")
    return DeterministicModel(
        {
            TaskAnalysis: analyze,
            ImplementationPlan: lambda _: ImplementationPlan(
                summary="Add query validation, slice products, and verify the response contract",
                steps=(
                    PlanStep(
                        order=1,
                        description="Add bounded offset and limit query parameters",
                        expected_files=("sample_api/app.py",),
                    ),
                    PlanStep(
                        order=2,
                        description="Cover pagination metadata and invalid limits",
                        expected_files=("tests/test_app.py",),
                        validation=("python -m pytest -q",),
                    ),
                ),
                proposed_commands=(command,),
            ),
            AnalysisReport: lambda prompt: AnalysisReport(
                summary=(
                    "The change remains inside the HTTP adapter and preserves existing boundaries"
                    if "boundaries" in prompt
                    else "The endpoint implementation and API tests are the only affected files"
                ),
                findings=(
                    Finding(
                        title="Response contract changes",
                        detail="Clients now receive an object with items and pagination metadata.",
                        severity=Severity.WARNING,
                        paths=("sample_api/app.py",),
                    ),
                ),
            ),
            ImplementationProposal: proposal,
            FailureDiagnosis: lambda _: FailureDiagnosis(
                summary="The deterministic demo change did not pass its validation suite",
                likely_causes=("The sample repository differs from the bundled baseline",),
                repair_strategy=("Restore the sample baseline and rerun the documented task",),
            ),
            ReviewResult: lambda _: ReviewResult(
                summary="Pagination is bounded, explicit, and covered by focused API tests",
                blocking=False,
            ),
            FinalReport: lambda _: FinalReport(
                outcome=RunStatus.COMPLETED,
                summary="Added bounded product pagination and verified the sample API tests",
            ),
        }
    )


def _context_hash(prompt: str, path: str) -> str:
    match = re.search(rf"--- {re.escape(path)}\n(.*?)(?=\n\n--- |\Z)", prompt, re.DOTALL)
    if match is None:
        raise ValueError(f"Bundled demo requires repository context for {path}")
    return hashlib.sha256(match.group(1).encode()).hexdigest()
