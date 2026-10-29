from app.modules.recruitment.service import RecruitmentService
from app.tools.contracts import ToolContext
from app.tools.recruitment_search.schema import (
    RecruitmentSearchInput,
    RecruitmentSearchItem,
    RecruitmentSearchOutput,
)


class RecruitmentSearchHandler:
    def __init__(self, service: RecruitmentService) -> None:
        self.service = service

    async def __call__(
        self, payload: RecruitmentSearchInput, context: ToolContext
    ) -> RecruitmentSearchOutput:
        del context
        hits = await self.service.search(payload.query, limit=payload.max_results)
        return RecruitmentSearchOutput(
            query=payload.query,
            results=[
                RecruitmentSearchItem(
                    title=hit.job.title,
                    company=hit.job.company,
                    city=" ".join(filter(None, [hit.job.city, hit.job.district])),
                    education=hit.job.education,
                    experience=hit.job.experience,
                    salary=hit.job.salary_text,
                    benefits=hit.job.benefits,
                    work_schedule=hit.job.work_schedule,
                    excerpt=hit.excerpt,
                    source_url=hit.job.source_url,
                    score=hit.score,
                )
                for hit in hits
            ],
        )
