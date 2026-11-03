"""API tracing lifecycle and concurrent request isolation, without paid models."""
import asyncio
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from text2sql_mvp.app import api
from text2sql_mvp.app.text2sql import PipelineResult


def result(question='One', error=''):
    return PipelineResult(question, [], [], '', 'select 1', [], error=error)


def test_disabled_does_not_import_telemetry(monkeypatch):
    monkeypatch.delenv('TEXT2SQL_TRACING', raising=False)
    monkeypatch.setitem(sys.modules, 'text2sql_mvp.app.telemetry', None)
    monkeypatch.setattr(api, 'run_pipeline_async', AsyncMock(return_value=result()))
    with TestClient(api.app) as client:
        response = client.post('/ask', json={'question': 'One'})
    assert response.status_code == 200
    assert 'x-trace-id' not in response.headers


def test_missing_dependencies_fail_at_startup(monkeypatch):
    monkeypatch.setenv('TEXT2SQL_TRACING', 'true')
    monkeypatch.setitem(sys.modules, 'text2sql_mvp.app.telemetry', None)
    with pytest.raises(RuntimeError, match='uv sync --extra tracing'):
        with TestClient(api.app):
            pass


@pytest.fixture
def tracing(monkeypatch):
    pytest.importorskip('openinference.instrumentation.pydantic_ai')
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from text2sql_mvp.app import telemetry
    exporter = InMemorySpanExporter()
    provider = telemetry.create_tracer_provider(exporter)
    monkeypatch.setattr(telemetry, 'create_tracer_provider', lambda: provider)
    monkeypatch.setenv('TEXT2SQL_TRACING', 'true')
    return provider, exporter


@pytest.mark.asyncio
async def test_concurrent_requests_have_separate_agent_traces(monkeypatch, tracing):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    provider, exporter = tracing
    previous = Agent._instrument_default
    agent = Agent(TestModel(custom_output_text='select 1'))
    arrived = 0
    ready = asyncio.Event()

    async def pipeline(question, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=5)
        await agent.run(question)
        return result(question)

    monkeypatch.setattr(api, 'run_pipeline_async', pipeline)
    async with api.app.router.lifespan_context(api.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
            responses = await asyncio.gather(*[
                client.post('/ask', json={'question': q}) for q in ['One', 'Two']
            ])
            health = await client.get('/health')
            assert 'x-trace-id' not in health.headers
    assert Agent._instrument_default is previous
    assert all(r.status_code == 200 for r in responses)
    ids = {r.headers['x-trace-id'] for r in responses}
    assert len(ids) == 2
    spans = exporter.get_finished_spans()  # flushed on shutdown
    assert {format(s.context.trace_id, '032x') for s in spans} == ids
    for trace_id in ids:
        group = [s for s in spans if format(s.context.trace_id, '032x') == trace_id]
        assert {'CHAIN', 'AGENT', 'LLM'} <= {s.attributes.get('openinference.span.kind') for s in group}
        root, = [s for s in group if s.name == 'text2sql.question']
        assert root.parent is None
        assert root.attributes['output.value'] == 'select 1'


@pytest.mark.parametrize('raises', [True, False])
def test_error_trace_and_header(monkeypatch, tracing, raises):
    _, exporter = tracing
    mock = AsyncMock(side_effect=RuntimeError('private error')) if raises else AsyncMock(return_value=result(error='private error'))
    monkeypatch.setattr(api, 'run_pipeline_async', mock)
    with TestClient(api.app) as client:
        response = client.post('/ask', json={'question': 'One'})
    assert response.status_code == (500 if raises else 502)
    root, = exporter.get_finished_spans()
    assert response.headers['x-trace-id'] == format(root.context.trace_id, '032x')
    assert root.status.description == 'application_failure'
    assert not root.events
