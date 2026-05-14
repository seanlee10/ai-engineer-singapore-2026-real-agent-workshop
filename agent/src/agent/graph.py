"""LangGraph RAG agent with OpenSearch retriever and GPT-4o-mini.

Retrieves relevant documents from OpenSearch, then generates a response
using GPT-4o-mini with the retrieved context.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import aiohttp
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime
from openinference.instrumentation.langchain import (
    LangChainInstrumentor,
    get_current_span,
)
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opensearchpy import AsyncOpenSearch
from opentelemetry import trace
from pydantic import Field
from typing_extensions import TypedDict

from agent.instrumentation import tracer_provider

tracer = tracer_provider.get_tracer(__name__)

# --- RAG prompt ---
RAG_TEMPLATE = """
You are an AI assistant tasked with answering questions based on provided context. Your goal is to provide accurate and relevant answers using only the information given.

Here is the context you should use to answer the question:

<context>
{context}
</context>

Now, here is the question you need to answer:

<question>
{query}
</question>
"""

rag_prompt = ChatPromptTemplate.from_template(RAG_TEMPLATE)

# --- Async embedding helper ---
async def generate_embedding(input_text: str) -> List[float]:
    """Generate an embedding vector via OpenAI text-embedding-3-large."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f'Bearer {os.environ["OPENAI_API_KEY"]}',
                "Content-Type": "application/json",
            },
            json={
                "model": "text-embedding-3-large",
                "input": input_text,
                "dimensions": 1024,
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if "error" in data:
                raise RuntimeError(f"OpenAI embedding error: {data['error']}")
            embedding: List[float] = data["data"][0]["embedding"]
            return embedding



# --- Embedding span for drift monitoring ---
EMBEDDING_MODEL = "text-embedding-3-large"


def log_embedding_span(
    docs: List[Document],
    model_name: str = EMBEDDING_MODEL,
    parent_span: Any = None,
) -> None:
    """Log a dedicated EMBEDDING span with vectors and text for Arize drift monitoring."""
    chunks = [
        {
            "text": doc.page_content,
            "vector": doc.metadata.get("embedding", []),
            "source": doc.metadata.get("source", "unknown"),
        }
        for doc in docs
        if doc.metadata.get("embedding")
    ]
    if not chunks:
        return

    # Build context from the parent span (retriever span)
    ctx = trace.set_span_in_context(parent_span) if parent_span else None

    with tracer.start_as_current_span(
        "document_chunk_embeddings", context=ctx
    ) as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.EMBEDDING.value,
        )
        span.set_attribute(SpanAttributes.EMBEDDING_MODEL_NAME, model_name)
        span.set_attribute(
            SpanAttributes.EMBEDDING_INVOCATION_PARAMETERS,
            json.dumps({"model": model_name, "dimension": len(chunks[0]["vector"])}),
        )
        span.set_attribute(SpanAttributes.INPUT_VALUE, json.dumps({"chunk_count": len(chunks)}))
        span.set_attribute(SpanAttributes.INPUT_MIME_TYPE, "application/json")

        for i, chunk in enumerate(chunks):
            span.set_attribute(f"embedding.embeddings.{i}.embedding.text", chunk["text"])
            span.set_attribute(f"embedding.embeddings.{i}.embedding.vector", chunk["vector"])

        span.set_attribute(
            SpanAttributes.METADATA,
            json.dumps({"sources": [c["source"] for c in chunks]}),
        )
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, f"{len(chunks)} embeddings logged")


# --- Async OpenSearch retriever ---
class OpenSearchRetriever(BaseRetriever):
    """Retrieve documents from OpenSearch using kNN vector search."""

    k: int = 10
    client: Any = Field(description="AsyncOpenSearch client")
    index: str = Field(description="Index name to search")

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any = None,
        search_query: str = "",
    ) -> List[Document]:
        """Search OpenSearch with kNN vector search."""
        embedding = await generate_embedding(search_query or query)

        body: Dict[str, Any] = {
            "size": self.k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": embedding,
                        "k": self.k,
                    }
                }
            },
        }

        resp = await self.client.search(index=self.index, body=body)
        hits = resp.get("hits", {}).get("hits", [])

        docs = [
            Document(
                page_content=hit["_source"].get("chunk", ""),
                metadata={
                    **hit["_source"].get("metadata", {}),
                    "score": hit.get("_score", 0.0),
                    "embedding": hit["_source"].get("embedding", []),
                },
            )
            for hit in hits
        ]

        # Find the retriever span (child of the node span)
        retriever_span = None
        node_span = get_current_span()
        if node_span:
            node_span_id = node_span.get_span_context().span_id
            instrumentor = LangChainInstrumentor()
            tracer_obj = getattr(instrumentor, "_tracer", None)
            if tracer_obj:
                spans = getattr(tracer_obj, "_spans_by_run", {})
                for _, s in spans.items():
                    parent = getattr(s, "parent", None)
                    if parent and parent.span_id == node_span_id:
                        retriever_span = s
                        break
        log_embedding_span(docs, parent_span=retriever_span or node_span)

        return docs

    def _get_relevant_documents(
        self, query: str, **kwargs: Any
    ) -> List[Document]:
        """Not used — async version is preferred."""
        raise NotImplementedError("Use ainvoke() instead")


# --- Clients ---
opensearch_client = AsyncOpenSearch(
    hosts=[{"host": os.environ["HOST"], "port": int(os.environ.get("PORT", "9200"))}],
    use_ssl=False,
    verify_certs=False,
)
retriever = OpenSearchRetriever(client=opensearch_client, index=os.environ["INDEX"])
llm = ChatOpenAI(model="gpt-4o-mini")


# --- Graph state & config ---
class Context(TypedDict):
    """Context parameters for the agent."""

    my_configurable_param: str


@dataclass
class State:
    """Input state for the agent."""

    messages: List[AnyMessage] = field(default_factory=list)
    docs: List[Document] = field(default_factory=list)
    search_query: str = ""


def _extract_query(message: Any) -> str:
    """Extract text content from a message (handles both objects and dicts)."""
    if hasattr(message, "content"):
        return str(message.content)
    if isinstance(message, dict):
        return str(message.get("content", str(message)))
    return str(message)


# --- Graph nodes ---
async def retrieve(state: State, runtime: Runtime[Context]) -> Dict[str, Any]:
    """Retrieve relevant documents from OpenSearch."""
    query = _extract_query(state.messages[-1])
    docs = await retriever.ainvoke(query, search_query=state.search_query)
    return {"docs": docs}

async def call_model(state: State, runtime: Runtime[Context]) -> Dict[str, Any]:
    """Generate a response using retrieved context and GPT-4o-mini."""
    query = _extract_query(state.messages[-1])

    context = "\n\n".join(doc.page_content for doc in state.docs)
    chain = rag_prompt | llm | StrOutputParser()
    response = await chain.ainvoke({"query": query, "context": context})

    return {"messages": [AIMessage(content=response)]}


# --- Define the graph ---
graph = (
    StateGraph(State, context_schema=Context)
    .add_node(retrieve)
    .add_node(call_model)
    .add_edge("__start__", "retrieve")
    .add_edge("retrieve", "call_model")
    .compile(name="Self RAG")
)
