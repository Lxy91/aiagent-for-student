from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import JobChunkModel, JobPostingModel
from app.infrastructure.vector.qdrant import QdrantRecruitmentStore, VectorChunk
from app.modules.recruitment.schemas import (
    JobImportItem,
    JobImportResponse,
    JobResponse,
    JobSearchHit,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(_clean(value) for value in values if _clean(value)))


def build_searchable_text(item: JobImportItem) -> str:
    fields = [
        f"职位：{item.title}",
        f"公司：{item.company}",
        f"地点：{' '.join(filter(None, [item.city, item.district]))}",
        f"学历：{item.education}",
        f"经验：{item.experience}",
        f"薪资：{item.salary_text}",
        f"工作时长：{item.work_schedule}",
        f"福利待遇：{'、'.join(_unique(item.benefits))}",
        f"岗位标签：{'、'.join(_unique(item.tags))}",
        f"职位要求：{item.requirements}",
        f"职位描述：{item.description}",
    ]
    return "\n".join(_clean(field) for field in fields if _clean(field.split("：", 1)[-1]))


def chunk_text(text: str, *, max_chars: int = 900, overlap: int = 100) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pending = paragraph
        while pending:
            capacity = max_chars - len(current) - (1 if current else 0)
            if capacity <= 0:
                chunks.append(current)
                current = current[-overlap:] if overlap else ""
                continue
            segment = pending[:capacity]
            current = f"{current}\n{segment}".strip()
            pending = pending[capacity:]
            if len(current) >= max_chars:
                chunks.append(current)
                current = current[-overlap:] if overlap else ""
    if current and (not chunks or current != chunks[-1]):
        chunks.append(current)
    return chunks or [text]


@dataclass
class _ImportCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    chunks: int = 0


class RecruitmentService:
    def __init__(
        self,
        session: AsyncSession,
        vector_store: QdrantRecruitmentStore | None = None,
    ) -> None:
        self.session = session
        self.vector_store = vector_store

    async def import_jobs(self, items: list[JobImportItem]) -> JobImportResponse:
        counts = _ImportCounts()
        changed_job_ids: set[str] = set()
        for payload in items:
            searchable = build_searchable_text(payload)
            digest = hashlib.sha256(searchable.encode("utf-8")).hexdigest()
            now = datetime.now(UTC).replace(tzinfo=None)
            model = await self.session.scalar(
                select(JobPostingModel).where(
                    JobPostingModel.source == payload.source,
                    JobPostingModel.external_id == payload.external_id,
                )
            )
            if model is None:
                model = JobPostingModel(
                    id=str(uuid4()),
                    source=payload.source,
                    external_id=payload.external_id,
                    source_url=str(payload.source_url),
                    title=payload.title,
                    requirements=payload.requirements,
                    description=payload.description,
                    searchable_text=searchable,
                    content_hash=digest,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self.session.add(model)
                counts.inserted += 1
            elif model.content_hash == digest:
                model.last_seen_at = now
                model.status = "active"
                counts.unchanged += 1
                continue
            else:
                counts.updated += 1
                await self.session.execute(
                    delete(JobChunkModel).where(JobChunkModel.job_id == model.id)
                )
            for field in (
                "company",
                "city",
                "district",
                "education",
                "experience",
                "salary_text",
                "salary_min",
                "salary_max",
                "salary_months",
                "requirements",
                "work_schedule",
                "description",
                "published_at",
            ):
                setattr(model, field, getattr(payload, field))
            model.source_url = str(payload.source_url)
            model.title = payload.title
            model.benefits = _unique(payload.benefits)
            model.tags = _unique(payload.tags)
            model.raw_json = payload.raw_json
            model.searchable_text = searchable
            model.content_hash = digest
            model.status = "active"
            model.last_seen_at = now
            await self.session.flush()
            changed_job_ids.add(model.id)
            for ordinal, content in enumerate(chunk_text(searchable)):
                self.session.add(
                    JobChunkModel(
                        id=str(uuid4()),
                        job_id=model.id,
                        ordinal=ordinal,
                        content=content,
                        token_estimate=max(1, len(content) // 2),
                    )
                )
                counts.chunks += 1
        await self.session.commit()
        if self.vector_store:
            for job_id in changed_job_ids:
                try:
                    await self.sync_job_vectors(job_id)
                except Exception:
                    # MySQL remains the source of truth. A full resync command repairs
                    # Qdrant after temporary model, network, or service failures.
                    continue
        return JobImportResponse(**counts.__dict__)

    async def list_jobs(
        self, *, city: str = "", education: str = "", experience: str = "", limit: int = 50
    ) -> list[JobResponse]:
        query = select(JobPostingModel).where(JobPostingModel.status == "active")
        if city:
            query = query.where(JobPostingModel.city.contains(city))
        if education:
            query = query.where(JobPostingModel.education.contains(education))
        if experience:
            query = query.where(JobPostingModel.experience.contains(experience))
        result = await self.session.scalars(
            query.order_by(JobPostingModel.last_seen_at.desc()).limit(limit)
        )
        return [self._response(item) for item in result]

    async def search(self, query: str, *, limit: int = 10) -> list[JobSearchHit]:
        if self.vector_store:
            try:
                vector_hits = await self._vector_search(query, limit=limit)
                if vector_hits:
                    return vector_hits
            except Exception:
                pass
        return await self._keyword_search(query, limit=limit)

    async def _vector_search(self, query: str, *, limit: int) -> list[JobSearchHit]:
        if self.vector_store is None:
            return []
        matches = await self.vector_store.search(query, limit=min(100, limit * 4))
        best_by_job = {}
        for match in matches:
            if match.job_id and match.job_id not in best_by_job:
                best_by_job[match.job_id] = match
        if not best_by_job:
            return []
        result = await self.session.scalars(
            select(JobPostingModel).where(
                JobPostingModel.id.in_(best_by_job),
                JobPostingModel.status == "active",
            )
        )
        jobs = {item.id: item for item in result}
        hits: list[JobSearchHit] = []
        for job_id, match in best_by_job.items():
            item = jobs.get(job_id)
            if item is None:
                continue
            hits.append(
                JobSearchHit(
                    job=self._response(item),
                    score=round(match.score, 4),
                    excerpt=self._excerpt(match.content, query.split()[0] if query.split() else ""),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def _keyword_search(self, query: str, *, limit: int) -> list[JobSearchHit]:
        terms = list(dict.fromkeys(re.findall(r"[\w\u4e00-\u9fff]+", query.lower())))[:12]
        if not terms:
            return []
        candidates = await self.session.scalars(
            select(JobPostingModel)
            .where(
                JobPostingModel.status == "active",
                or_(*(JobPostingModel.searchable_text.contains(term) for term in terms)),
            )
            .order_by(JobPostingModel.last_seen_at.desc())
            .limit(200)
        )
        hits: list[JobSearchHit] = []
        for item in candidates:
            haystack = item.searchable_text.lower()
            matched = [term for term in terms if term in haystack]
            score = len(matched) / len(terms)
            title_bonus = sum(term in item.title.lower() for term in terms) * 0.25
            excerpt = self._excerpt(item.searchable_text, matched[0] if matched else "")
            hits.append(
                JobSearchHit(
                    job=self._response(item), score=round(score + title_bonus, 4), excerpt=excerpt
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    async def sync_job_vectors(self, job_id: str) -> int:
        if self.vector_store is None:
            return 0
        chunks = await self._vector_chunks(job_id=job_id)
        return await self.vector_store.replace_job(job_id, chunks)

    async def rebuild_vector_index(self) -> int:
        if self.vector_store is None:
            return 0
        return await self.vector_store.recreate(await self._vector_chunks())

    async def _vector_chunks(self, *, job_id: str | None = None) -> list[VectorChunk]:
        query = (
            select(JobChunkModel, JobPostingModel)
            .join(JobPostingModel, JobPostingModel.id == JobChunkModel.job_id)
            .where(JobPostingModel.status == "active")
            .order_by(JobPostingModel.id, JobChunkModel.ordinal)
        )
        if job_id:
            query = query.where(JobPostingModel.id == job_id)
        rows = (await self.session.execute(query)).all()
        return [
            VectorChunk(
                id=chunk.id,
                job_id=job.id,
                content=chunk.content,
                source=job.source,
                title=job.title,
                company=job.company,
                city=job.city,
                education=job.education,
                experience=job.experience,
                source_url=job.source_url,
            )
            for chunk, job in rows
        ]

    @staticmethod
    def _excerpt(text: str, term: str, radius: int = 180) -> str:
        position = text.lower().find(term.lower()) if term else 0
        start = max(0, position - radius)
        end = min(len(text), position + len(term) + radius)
        return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")

    @staticmethod
    def _response(item: JobPostingModel) -> JobResponse:
        return JobResponse(
            id=UUID(item.id),
            source=item.source,
            external_id=item.external_id,
            source_url=item.source_url,
            title=item.title,
            company=item.company,
            city=item.city,
            district=item.district,
            education=item.education,
            experience=item.experience,
            salary_text=item.salary_text,
            salary_min=item.salary_min,
            salary_max=item.salary_max,
            salary_months=item.salary_months,
            requirements=item.requirements,
            benefits=item.benefits or [],
            work_schedule=item.work_schedule,
            description=item.description,
            tags=item.tags or [],
            status=item.status,
            published_at=item.published_at,
            first_seen_at=item.first_seen_at,
            last_seen_at=item.last_seen_at,
        )
