"""
Verified AI Training-Data Collection & Curation Service.

Collects, organizes, and labels verified SEO issue-recommendation pairs
to prepare fine-tuning datasets for open-weight Gemma checkpoints (LoRA / QLoRA).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..database import SessionLocal, AITrainingExample

logger = logging.getLogger("aviance.ai.training_collector")


class TrainingExampleInput(BaseModel):
    website_type: str = "General"
    page_type: str = "Landing"
    verified_issue: str
    observed_evidence: str
    relevant_documentation: str = ""
    correct_explanation: str
    correct_recommendation: str
    incorrect_recommendation_examples: List[str] = Field(default_factory=list)
    reviewer_notes: str = ""


class TrainingExampleOutput(BaseModel):
    example_id: str
    website_type: str
    page_type: str
    verified_issue: str
    observed_evidence: str
    relevant_documentation: str
    correct_explanation: str
    correct_recommendation: str
    incorrect_recommendation_examples: List[str]
    review_status: str
    reviewer_notes: str
    created_at: str


class AITrainingDataCollector:
    """
    Manages verified training datasets for future Gemma fine-tuning.
    """

    def add_example(self, data: TrainingExampleInput, auto_approve: bool = False) -> str:
        """Adds a new candidate training example."""
        example_id = f"TRN-{uuid.uuid4().hex[:8].upper()}"
        status = "APPROVED" if auto_approve else "PENDING_REVIEW"
        try:
            with SessionLocal() as db:
                row = AITrainingExample(
                    example_id=example_id,
                    website_type=data.website_type,
                    page_type=data.page_type,
                    verified_issue=data.verified_issue,
                    observed_evidence=data.observed_evidence,
                    relevant_documentation=data.relevant_documentation,
                    correct_explanation=data.correct_explanation,
                    correct_recommendation=data.correct_recommendation,
                    incorrect_recommendation_examples=json.dumps(data.incorrect_recommendation_examples),
                    review_status=status,
                    reviewer_notes=data.reviewer_notes,
                    created_at=datetime.utcnow()
                )
                db.add(row)
                db.commit()
            return example_id
        except Exception as exc:
            logger.error(f"Failed to record training example: {exc}")
            return ""

    def update_status(self, example_id: str, new_status: str, notes: Optional[str] = None) -> bool:
        """Updates review status of a training example."""
        valid_statuses = {"PENDING_REVIEW", "APPROVED", "REJECTED", "NEEDS_CORRECTION"}
        if new_status not in valid_statuses:
            return False

        try:
            with SessionLocal() as db:
                row = db.query(AITrainingExample).filter(AITrainingExample.example_id == example_id).first()
                if not row:
                    return False
                row.review_status = new_status
                if notes is not None:
                    row.reviewer_notes = notes
                db.commit()
            return True
        except Exception as exc:
            logger.error(f"Failed to update training example {example_id}: {exc}")
            return False

    def list_examples(self, status: Optional[str] = None, limit: int = 100) -> List[TrainingExampleOutput]:
        """Lists training examples filtered by review status."""
        try:
            with SessionLocal() as db:
                q = db.query(AITrainingExample)
                if status:
                    q = q.filter(AITrainingExample.review_status == status.upper())
                rows = q.order_by(AITrainingExample.created_at.desc()).limit(limit).all()
                out = []
                for r in rows:
                    try:
                        inc = json.loads(r.incorrect_recommendation_examples) if isinstance(r.incorrect_recommendation_examples, str) else []
                    except Exception:
                        inc = []
                    out.append(
                        TrainingExampleOutput(
                            example_id=r.example_id,
                            website_type=r.website_type,
                            page_type=r.page_type,
                            verified_issue=r.verified_issue,
                            observed_evidence=r.observed_evidence,
                            relevant_documentation=r.relevant_documentation,
                            correct_explanation=r.correct_explanation,
                            correct_recommendation=r.correct_recommendation,
                            incorrect_recommendation_examples=inc,
                            review_status=r.review_status,
                            reviewer_notes=r.reviewer_notes,
                            created_at=r.created_at.isoformat() if r.created_at else ""
                        )
                    )
                return out
        except Exception as exc:
            logger.error(f"Failed to list training examples: {exc}")
            return []

    def export_dataset_jsonl(self, status: str = "APPROVED") -> str:
        """
        Exports approved training examples in standard instruction fine-tuning JSONL format.
        Compatible with Hugging Face, SFTTrainer, and LoRA/QLoRA pipelines.
        """
        examples = self.list_examples(status=status, limit=1000)
        lines = []
        for ex in examples:
            prompt = (
                f"### Instruction:\nAnalyze the verified SEO issue for a {ex.website_type} website ({ex.page_type} page).\n"
                f"Issue: {ex.verified_issue}\nEvidence: {ex.observed_evidence}\n"
                f"Relevant Documentation: {ex.relevant_documentation}\n\n"
                f"### Response:\nExplanation: {ex.correct_explanation}\nRecommendation: {ex.correct_recommendation}"
            )
            entry = {
                "id": ex.example_id,
                "prompt": prompt,
                "chosen": ex.correct_recommendation,
                "rejected": ex.incorrect_recommendation_examples[0] if ex.incorrect_recommendation_examples else ""
            }
            lines.append(json.dumps(entry))
        return "\n".join(lines)


training_collector = AITrainingDataCollector()

