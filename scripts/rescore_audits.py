"""Re-score stored audits with the spec engine (ruleset 1.0.0) from their stored evidence.

No network requests are made: checks that need probes, rendering or connectors become 'Not measured'.
Published client report snapshots are NOT changed (they are frozen by design).

Usage:  .venv\\Scripts\\python.exe scripts\\rescore_audits.py [--dry-run]
Back up seo_platform.db first.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)

from backend.database import Audit, SessionLocal  # noqa: E402
from backend.main import RULESET_VERSION, run_spec_engine  # noqa: E402


def main(dry_run: bool) -> None:
    with SessionLocal() as db:
        for a in db.query(Audit).order_by(Audit.id).all():
            try:
                res = json.loads(a.result_json) if isinstance(a.result_json, str) else (a.result_json or {})
            except ValueError:
                print(f"#{a.id} skipped: unreadable JSON")
                continue
            if not res.get("pages"):
                print(f"#{a.id} {a.target_url}: no stored page evidence, left unchanged (score {a.score})")
                continue
            if (res.get("seo_engine") or {}).get("ruleset_version") == RULESET_VERSION:
                print(f"#{a.id} {a.target_url}: already on ruleset {RULESET_VERSION} (score {a.score})")
                continue
            old = a.score
            if "page_findings" not in res and res.get("issues") and "check_id" not in res["issues"][0]:
                res["page_findings"] = res["issues"]
            payload = run_spec_engine(res)
            new = payload["score"]["overall"]
            res["rescored_from_legacy"] = {"previous_score": old, "ruleset_version": RULESET_VERSION,
                                           "note": "Re-scored from stored evidence; probe/render/connector checks not measured."}
            print(f"#{a.id} {a.target_url}: {old} -> {new} ({payload['score']['grade']}); gate {'pass' if payload['integrity']['verification_gate']['passed'] else 'FAIL'}")
            if not dry_run:
                a.result_json = json.dumps(res, default=str)
                a.score = new
        if not dry_run:
            db.commit()
            print("Committed.")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
