"""Both transports use the same pipeline core and release owned connections."""
from unittest.mock import AsyncMock

import pytest

from text2sql_mvp.app import text2sql


@pytest.fixture
def core(monkeypatch, engine):
    monkeypatch.setattr(text2sql, "get_engine", lambda: engine)
    mock = AsyncMock(return_value=text2sql.PipelineResult(
        question="Sales?", expanded_queries=[], retrieved_tables=[],
        dbml_context="", generated_sql="SELECT 1", rows=[],
    ))
    monkeypatch.setattr(text2sql, "_run_async", mock)
    return mock


def test_sync_entrypoint(core):
    assert text2sql.run_pipeline("Sales?", narrate=False) is core.return_value
    question, conn, dialect, narrate = core.call_args.args
    assert (question, dialect, narrate) == ("Sales?", "sqlite", False)
    assert conn.closed


@pytest.mark.asyncio
async def test_async_entrypoint_repeated_calls(core):
    for _ in range(2):
        assert await text2sql.run_pipeline_async("Sales?") is core.return_value
        assert core.call_args.args[1].closed
    assert core.await_count == 2


@pytest.mark.asyncio
async def test_async_failure_releases_connection(core):
    core.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError, match="failed"):
        await text2sql.run_pipeline_async("Sales?")
    assert core.call_args.args[1].closed


@pytest.mark.asyncio
async def test_caller_owned_connection_stays_open(core, engine):
    with engine.connect() as conn:
        await text2sql.run_pipeline_async("Sales?", conn=conn)
        assert not conn.closed
        assert core.call_args.args[1] is conn
