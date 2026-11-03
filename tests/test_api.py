"""HTTP contract tests without external model calls."""
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from text2sql_mvp.app import api
from text2sql_mvp.app.text2sql import PipelineResult


@pytest.fixture
def pipeline(monkeypatch):
    mock = AsyncMock(return_value=PipelineResult(
        question="Total sales?", expanded_queries=[], retrieved_tables=["orders"],
        dbml_context="Table orders {}", generated_sql="SELECT 1", rows=[],
        answer="One.",
    ))
    monkeypatch.setattr(api, "run_pipeline_async", mock)
    return mock


@pytest.fixture
def client():
    with TestClient(api.app) as client:
        yield client


def test_health_and_docs(client, pipeline):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    assert "/ask" in client.get("/openapi.json").json()["paths"]
    pipeline.assert_not_called()


def test_ask_defaults_and_database_values(client, pipeline):
    pipeline.return_value.rows = [{"total": Decimal("12.50"), "day": date(2026, 1, 1), "value": None}]
    response = client.post("/ask", json={"question": " Total sales? "})
    assert response.status_code == 200
    assert response.json()["generated_sql"] == "SELECT 1"
    assert response.json()["rows"] == [{"total": "12.50", "day": "2026-01-01", "value": None}]
    pipeline.assert_awaited_once_with("Total sales?", narrate=True, verbose=False)


def test_ask_options(client, pipeline):
    response = client.post("/ask", json={"question": "Total sales?", "narrate": False, "verbose": True})
    assert response.status_code == 200
    pipeline.assert_awaited_once_with("Total sales?", narrate=False, verbose=True)


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": " \n "},
    {"question": None}, {"question": 123}, {"question": "Sales?", "unknown": True}])
def test_invalid_request(client, pipeline, payload):
    assert client.post("/ask", json=payload).status_code == 422
    pipeline.assert_not_called()


def test_pipeline_error(client, pipeline):
    pipeline.return_value.error = "Schema lookup returned no tables."
    response = client.post("/ask", json={"question": "Total sales?"})
    assert response.status_code == 502
    assert response.json()["error"] == pipeline.return_value.error


def test_unexpected_failure(client, pipeline):
    pipeline.side_effect = RuntimeError("private connection details")
    response = client.post("/ask", json={"question": "Total sales?"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Text2SQL request failed"}
