"""HTTP interface for the same pipeline used by the CLI."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, nullcontext
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

# Load configuration before importing modules that read model settings.
load_dotenv()

from .text2sql import PipelineResult, run_pipeline_async

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.tracer_provider = None
    if os.getenv("TEXT2SQL_TRACING", "").lower() not in {"1", "true", "yes"}:
        yield
        return
    try:
        from .telemetry import tracing_session
    except ImportError as exc:
        raise RuntimeError(
            "Tracing requires: uv sync --extra tracing; start with "
            "uv run --extra tracing uvicorn text2sql_mvp.app.api:app"
        ) from exc
    with tracing_session() as provider:
        app.state.tracer_provider = provider
        try:
            yield
        finally:
            app.state.tracer_provider = None


app = FastAPI(title="Text2SQL", version="0.1.0", lifespan=lifespan)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    narrate: bool = True
    verbose: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check; does not call the database or model endpoints."""
    return {"status": "ok"}


@app.post("/ask", response_model=PipelineResult, responses={
    502: {"model": PipelineResult, "description": "The pipeline returned an error"},
    500: {"description": "Unexpected pipeline failure"},
})
async def ask(request: AskRequest, response: Response, http_request: Request) -> PipelineResult:
    """Generate and execute SQL, optionally narrating the results."""
    provider = getattr(http_request.app.state, "tracer_provider", None)
    span_context = nullcontext(None)
    headers = {}
    if provider is not None:
        from .telemetry import question_span
        from opentelemetry.trace import Status, StatusCode
        span_context = question_span(provider, request.question)
    try:
        with span_context as span:
            if span is not None:
                headers["X-Trace-ID"] = format(span.get_span_context().trace_id, "032x")
                response.headers.update(headers)
            result = await run_pipeline_async(
                request.question, narrate=request.narrate, verbose=request.verbose,
            )
            if span is not None:
                if result.error:
                    span.set_status(Status(StatusCode.ERROR, "application_failure"))
                else:
                    span.set_attribute("output.value", result.generated_sql)
    except Exception:
        log.exception("Text2SQL request failed")
        raise HTTPException(status_code=500, detail="Text2SQL request failed", headers=headers) from None
    if result.error:
        response.status_code = 502
    return result
