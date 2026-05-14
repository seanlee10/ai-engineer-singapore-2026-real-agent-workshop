"""Arize AX tracing instrumentation for the LangGraph agent."""

import os
import warnings

warnings.filterwarnings("ignore", message=".*Calling .text\\(\\).*")

from arize.otel import register, Transport, Endpoint
from openinference.instrumentation.langchain import LangChainInstrumentor

ARIZE_ENDPOINT = os.getenv("ARIZE_ENDPOINT", Endpoint.ARIZE)

tracer_provider = register(
    endpoint=ARIZE_ENDPOINT,
    transport=Transport.GRPC if ARIZE_ENDPOINT.endswith("/v1") else Transport.HTTP,
    space_id=os.getenv("ARIZE_SPACE_ID"),
    api_key=os.getenv("ARIZE_API_KEY"),
    project_name=os.getenv("ARIZE_PROJECT_NAME"),
    set_global_tracer_provider=False,
)

LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
