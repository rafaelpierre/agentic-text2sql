"""CLI opt-in and telemetry tests use explicit local test models, never paid APIs."""
from types import SimpleNamespace
import sys

import pytest
from typer.testing import CliRunner
import cli


def result(error=''):
    return SimpleNamespace(error=error, generated_sql='select 1', rows=[], answer='')


def test_default_cli_does_not_load_telemetry(monkeypatch):
    monkeypatch.setitem(sys.modules, 'text2sql_mvp.app.telemetry', None)
    monkeypatch.setattr(cli, 'run_pipeline', lambda *a, **k: result())
    output = CliRunner().invoke(cli.app, ['ask', 'Return one'])
    assert output.exit_code == 0
    assert 'select 1' in output.stdout
    assert 'Trace ID' not in output.stdout


def test_missing_optional_dependencies_give_install_command(monkeypatch):
    monkeypatch.setitem(sys.modules, 'text2sql_mvp.app.telemetry', None)
    monkeypatch.setattr(cli, 'run_pipeline', lambda *a, **k: pytest.fail('Pipeline ran'))
    output = CliRunner().invoke(cli.app, ['ask', 'Return one', '--trace'])
    assert output.exit_code == 2
    assert 'uv sync --extra tracing' in output.output


@pytest.fixture
def telemetry(monkeypatch):
    pytest.importorskip('openinference.instrumentation.pydantic_ai')
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from text2sql_mvp.app import telemetry
    exporter = InMemorySpanExporter()
    factory = telemetry.create_tracer_provider
    provider = factory(exporter)
    monkeypatch.setattr(telemetry, 'create_tracer_provider', lambda: provider)
    return telemetry, provider, exporter


def test_trace_auto_instruments_and_restores_previous_settings(monkeypatch, telemetry):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    _, provider, exporter = telemetry
    previous = Agent._instrument_default
    def pipeline(*a, **k):
        Agent(TestModel(custom_output_text='select 1')).run_sync('Return one')
        return result()
    monkeypatch.setattr(cli, 'run_pipeline', pipeline)
    output = CliRunner().invoke(cli.app, ['ask', 'Return one', '--trace', '--no-narrate'])
    assert output.exit_code == 0, output.exception
    spans = exporter.get_finished_spans()
    assert {'CHAIN', 'AGENT', 'LLM'} <= {s.attributes.get('openinference.span.kind') for s in spans}
    assert len({s.context.trace_id for s in spans}) == 1
    assert format(spans[0].context.trace_id, '032x') in output.stdout
    assert Agent._instrument_default is previous


@pytest.mark.parametrize('raises', [False, True])
def test_failure_flushes_without_recording_raw_error(monkeypatch, telemetry, raises):
    from pydantic_ai import Agent
    _, provider, exporter = telemetry
    previous = Agent._instrument_default
    calls = []
    flush = provider.force_flush
    shutdown = provider.shutdown
    monkeypatch.setattr(provider, 'force_flush', lambda **k: calls.append('flush') or flush(**k))
    monkeypatch.setattr(provider, 'shutdown', lambda: calls.append('shutdown') or shutdown())
    def pipeline(*a, **k):
        if raises:
            raise RuntimeError('private-provider-response')
        return result(error='private-provider-response')
    monkeypatch.setattr(cli, 'run_pipeline', pipeline)
    output = CliRunner().invoke(cli.app, ['ask', 'Return one', '--trace'])
    assert output.exit_code != 0
    assert calls == ['flush', 'shutdown']
    root, = exporter.get_finished_spans()
    assert root.status.description == 'application_failure'
    assert not root.events
    assert Agent._instrument_default is previous
