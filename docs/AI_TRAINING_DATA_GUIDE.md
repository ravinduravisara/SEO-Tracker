# Curated Instruction Fine-Tuning Dataset Guide

## 1. Overview
The Training Data Collector (`backend/ai/training_collector.py`) automatically gathers, structures, and curates verified SEO issue-recommendation pairs. This dataset provides high-quality ground-truth training material for parameter-efficient fine-tuning (LoRA / QLoRA) on Gemma 4 models.

---

## 2. Dataset Pipeline & Review Lifecycle

```
[ Audit Triggered ]
         |
         v
[ Issue Verified by Ruleset ]
         |
         v
[ RAG Knowledge Retrieval ]
         |
         v
[ Candidate Pair Recorded in Database ] ---> Review Status: PENDING_REVIEW
         |
         +-----> Administrator Review via UI (Approve / Reject / Edit)
         |
         v
[ Status: APPROVED ]
         |
         v
[ Export to JSONL Format ] ---> Input for Gemma 4 LoRA / QLoRA Training
```

---

## 3. Training Pair Schema

Each training record conforms to standard instruction-tuning specifications:

```json
{
  "example_id": "TRN-C7FB8935",
  "website_type": "E-commerce",
  "page_type": "Product",
  "verified_issue": "Missing Self-Referencing Canonical Tag",
  "observed_evidence": "Page https://example.com/item returned HTTP 200 without canonical tag in HTML head.",
  "relevant_documentation": "Google Search Central: Consolidate Duplicate URLs",
  "correct_explanation": "Self-referencing canonical tags prevent search engines from treating parameter or session variants as separate indexing candidates.",
  "correct_recommendation": "Add <link rel='canonical' href='https://example.com/item'> in document head.",
  "incorrect_recommendation_examples": [
    "Treat this as a critical ranking penalty and delete parameter links."
  ],
  "review_status": "APPROVED",
  "reviewer_notes": "Calibrated against Google Search Central RFC 6596 guidance.",
  "created_at": "2026-10-25T10:00:00Z"
}
```

---

## 4. Fine-Tuning Export Format (JSONL)

When exported via `GET /api/admin/ai/training/export`, the system generates line-delimited JSON matching standard Alpaca / DPO training formats:

```json
{"id": "TRN-C7FB8935", "prompt": "### Instruction:\nAnalyze the verified SEO issue for a E-commerce website (Product page).\nIssue: Missing Self-Referencing Canonical Tag\nEvidence: Page https://example.com/item returned HTTP 200 without canonical tag in HTML head.\nRelevant Documentation: Google Search Central: Consolidate Duplicate URLs\n\n### Response:\nExplanation: Self-referencing canonical tags prevent search engines from treating parameter or session variants as separate indexing candidates.\nRecommendation: Add <link rel='canonical' href='https://example.com/item'> in document head.", "chosen": "Add <link rel='canonical' href='https://example.com/item'> in document head.", "rejected": "Treat this as a critical ranking penalty and delete parameter links."}
```

