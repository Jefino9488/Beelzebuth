from typing import List, Optional
from pydantic import BaseModel, Field

from injester.application.manager import manager

class DigestResult(BaseModel):
    topic: str
    markdown: str
    is_valid: bool
    verified_citations_count: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class DigestService:
    def __init__(self):
        self.mgr = manager

    def generate(self, topic: str, file_ids: Optional[List[str]] = None) -> DigestResult:
        """Devours information and synthesizes a readable, citation-audited Markdown document (.md)."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()

        markdown_doc, val_report = pipeline.generate_digest(
            sec_ctx=sec_ctx,
            topic_goal=topic,
            file_ids=file_ids,
        )

        return DigestResult(
            topic=topic,
            markdown=markdown_doc,
            is_valid=val_report.is_valid,
            verified_citations_count=len(val_report.verified_citation_index),
            errors=val_report.errors,
            warnings=val_report.warnings,
        )
