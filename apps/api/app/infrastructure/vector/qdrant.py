from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from app.core.config import Settings


@dataclass(frozen=True)
class VectorChunk:
    id: str
    job_id: str
    content: str
    source: str
    title: str
    company: str
    city: str
    education: str
    experience: str
    source_url: str


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    job_id: str
    content: str
    score: float


class TextEmbedder(Protocol):
    def embed(self, texts: list[str]) -> Iterator[np.ndarray]: ...

    def query_embed(self, query: str) -> Iterator[np.ndarray]: ...


class LazyFastEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: TextEmbedding | None = None

    def _get(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=self.cache_dir,
                lazy_load=True,
            )
        return self._model

    def embed(self, texts: list[str]) -> Iterator[np.ndarray]:
        return self._get().embed(texts)

    def query_embed(self, query: str) -> Iterator[np.ndarray]:
        return self._get().query_embed(query)


class QdrantRecruitmentStore:
    def __init__(
        self,
        *,
        client: QdrantClient,
        embedder: TextEmbedder,
        collection_name: str,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantRecruitmentStore:
        return cls(
            client=QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=settings.qdrant_timeout_seconds,
                check_compatibility=False,
            ),
            embedder=LazyFastEmbedder(
                model_name=settings.embedding_model, cache_dir=settings.embedding_cache_dir
            ),
            collection_name=settings.qdrant_collection,
        )

    async def health(self) -> bool:
        try:
            return await asyncio.to_thread(self.client.collection_exists, self.collection_name)
        except Exception:
            return False

    async def replace_job(self, job_id: str, chunks: Iterable[VectorChunk]) -> int:
        materialized = list(chunks)
        return await asyncio.to_thread(self._replace_job, job_id, materialized)

    def _replace_job(self, job_id: str, chunks: list[VectorChunk]) -> int:
        if self.client.collection_exists(self.collection_name):
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="job_id", match=models.MatchValue(value=job_id)
                            )
                        ]
                    )
                ),
                wait=True,
            )
        if not chunks:
            return 0
        vectors = [
            vector.tolist() for vector in self.embedder.embed([item.content for item in chunks])
        ]
        self._ensure_collection(len(vectors[0]))
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=item.id,
                    vector=vector,
                    payload=self._payload(item),
                )
                for item, vector in zip(chunks, vectors, strict=True)
            ],
            wait=True,
        )
        return len(chunks)

    async def recreate(self, chunks: Iterable[VectorChunk]) -> int:
        materialized = list(chunks)
        return await asyncio.to_thread(self._recreate, materialized)

    def _recreate(self, chunks: list[VectorChunk]) -> int:
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
        if not chunks:
            return 0
        vectors = [
            vector.tolist() for vector in self.embedder.embed([item.content for item in chunks])
        ]
        self._ensure_collection(len(vectors[0]))
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(id=item.id, vector=vector, payload=self._payload(item))
                for item, vector in zip(chunks, vectors, strict=True)
            ],
            wait=True,
        )
        return len(chunks)

    async def search(
        self,
        query: str,
        *,
        limit: int,
        city: str = "",
        education: str = "",
        experience: str = "",
    ) -> list[VectorMatch]:
        return await asyncio.to_thread(
            self._search,
            query,
            limit=limit,
            city=city,
            education=education,
            experience=experience,
        )

    def _search(
        self,
        query: str,
        *,
        limit: int,
        city: str,
        education: str,
        experience: str,
    ) -> list[VectorMatch]:
        if not self.client.collection_exists(self.collection_name):
            return []
        conditions = [models.FieldCondition(key="status", match=models.MatchValue(value="active"))]
        for key, value in (("city", city), ("education", education), ("experience", experience)):
            if value:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchText(text=value))
                )
        query_vector = next(self.embedder.query_embed(query)).tolist()
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            with_payload=True,
        )
        matches: list[VectorMatch] = []
        for point in response.points:
            payload = point.payload or {}
            matches.append(
                VectorMatch(
                    chunk_id=str(point.id),
                    job_id=str(payload.get("job_id", "")),
                    content=str(payload.get("content", "")),
                    score=float(point.score),
                )
            )
        return matches

    def _ensure_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        for field_name in ("job_id", "source", "status"):
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        for field_name in ("city", "education", "experience"):
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.TEXT,
                wait=True,
            )

    @staticmethod
    def _payload(item: VectorChunk) -> dict[str, Any]:
        return {
            "job_id": item.job_id,
            "content": item.content,
            "source": item.source,
            "title": item.title,
            "company": item.company,
            "city": item.city,
            "education": item.education,
            "experience": item.experience,
            "source_url": item.source_url,
            "status": "active",
        }
