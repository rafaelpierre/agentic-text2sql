"""Opt-in Phoenix/OpenInference telemetry. Importing this module performs no setup."""
import os
from contextlib import contextmanager
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
from opentelemetry.trace import Status, StatusCode
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings


def create_tracer_provider(exporter=None):
    endpoint = (os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT') or 'http://localhost:6006/v1/traces')
    headers = {'Authorization': 'Bearer ' + os.environ['PHOENIX_API_KEY']} if os.getenv('PHOENIX_API_KEY') else {}
    provider = TracerProvider(resource=Resource.create({'service.name': 'agentic-text2sql',
                                                       'openinference.project.name': os.getenv('PHOENIX_PROJECT_NAME') or 'agentic-text2sql'}))
    provider.add_span_processor(OpenInferenceSpanProcessor())
    provider.add_span_processor(BatchSpanProcessor(exporter or OTLPSpanExporter(endpoint=endpoint, headers=headers, timeout=5)))
    return provider


@contextmanager
def tracing_session():
    """Install instrumentation for a CLI invocation or an entire server lifetime."""

    provider = create_tracer_provider()
    previous = Agent._instrument_default
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, version=5))
    try:
        yield provider
    finally:
        Agent.instrument_all(previous)
        try:
            provider.force_flush(timeout_millis=5000)
        finally:
            provider.shutdown()


@contextmanager
def question_span(provider, question):
    """Create a question trace using context-local parentage for agent spans."""
    with provider.get_tracer('agentic-text2sql').start_as_current_span(
        'text2sql.question', record_exception=False, set_status_on_exception=False,
        attributes={'openinference.span.kind': 'CHAIN', 'input.value': question},
    ) as span:
        try:
            yield span
        except BaseException:
            span.set_status(Status(StatusCode.ERROR, 'application_failure'))
            raise


@contextmanager
def trace_question(question):
    """Instrument a CLI invocation and flush even when the application fails."""
    with tracing_session() as provider:
        with question_span(provider, question) as span:
            yield span
