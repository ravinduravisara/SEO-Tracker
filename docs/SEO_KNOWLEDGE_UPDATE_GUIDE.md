# Controlled SEO Knowledge Update & Rollback Guide

## 1. Overview
The SEO Knowledge Update Service allows administrators to safely refresh, update, and rollback Google Search Central specifications without restarting the application or risking documentation drift.

---

## 2. Cryptographic Content Hashing
Every document in the corpus is indexed with a SHA-256 hash calculated over its canonical text:
$$\text{Content Hash} = \text{SHA-256}(\text{Document Text})$$

When an update is executed:
* If the newly fetched content hash matches the stored document hash: the document is marked **UNCHANGED** and no database write occurs.
* If the hash differs: the document is updated, the previous version is archived in version history, and `knowledge_version` increments.

---

## 3. Administrative REST Endpoints

### 3.1 List Knowledge Documents
* **Endpoint**: `GET /api/admin/ai/knowledge`
* **Response**:
```json
{
  "active_version": "1.0.0",
  "total_documents": 13,
  "documents": [
    {
      "document_id": "DOC-CANONICAL-URLS",
      "title": "Consolidating Duplicate URLs with Canonical Tags",
      "source_url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
      "category": "Technical SEO",
      "publisher": "Google Search Central",
      "knowledge_version": "1.0.0",
      "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  ]
}
```

### 3.2 Trigger Documentation Refresh
* **Endpoint**: `POST /api/admin/ai/knowledge/refresh`
* **Action**: Re-evaluates all 13 authoritative documentation sources against upstream specifications.

### 3.3 Rollback to a Previous Version
* **Endpoint**: `POST /api/admin/ai/knowledge/rollback`
* **Payload**:
```json
{
  "target_version": "1.0.0"
}
```
* **Action**: Restores document state and active version pointer to the targeted release.

---

## 4. Safety Controls
1. **Thread-Safe Locks**: Updates acquire an exclusive mutex lock (`threading.Lock`) to prevent race conditions during concurrent searches.
2. **Immutable Active Version**: Previous versions are preserved in memory and persistent storage; an erroneous update can be restored in $< 1\text{ second}$.

