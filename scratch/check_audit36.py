import sys
sys.path.insert(0, ".")
import json
from backend.database import SessionLocal, Audit

db = SessionLocal()
a = db.query(Audit).filter(Audit.id == 36).first()
res = json.loads(a.result_json)
print("Score in DB:", a.score)
print("Keys in res:", list(res.keys()))
engine = res.get("seo_engine") or {}
print("SEO Engine overall:", engine.get("overall"))
print("SEO Engine grade:", engine.get("grade"))
print("SEO Engine weighted_sum:", engine.get("weighted_sum"))
print("SEO Engine vertical_profile:", engine.get("audit", {}).get("vertical_profile"))
print("\n--- Categories in Engine ---")
for cat in engine.get("categories", []):
    print(f"  {cat.get('name')}: score={cat.get('score')} weight={cat.get('weight')} raw={cat.get('raw')} cap={cat.get('confidence_cap')}")

print("\n--- Checks in Engine ---")
for c in engine.get("checks", []):
    print(f"  {c.get('id')} [{c.get('category')}]: {c.get('status')} (earned={c.get('points_earned', c.get('coverage'))}/{c.get('points')}) - {c.get('name')}")

