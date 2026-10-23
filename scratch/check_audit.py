import json
from backend.database import SessionLocal, Audit

with SessionLocal() as db:
    a = db.query(Audit).filter(Audit.id == 38).first()
    if a and a.result_json:
        data = json.loads(a.result_json)
        eng = data.get('seo_engine') or {}
        checks = {c['id']: c for c in eng.get('checks', [])}
        for cat in ('vertical', 'keyword', 'on_page', 'conversion'):
            print(f"\n=== Checks in {cat} ===")
            for chk_id, chk in checks.items():
                if chk.get('category') == cat:
                    print(f"  {chk_id}: {chk.get('name')} | status: {chk.get('status')} | pts available: {chk.get('points_available')} | pts earned: {chk.get('points_earned')} | credit: {chk.get('credit')} | coverage: {chk.get('coverage')}")
