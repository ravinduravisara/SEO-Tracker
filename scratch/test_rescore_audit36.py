import sys
sys.path.insert(0, ".")
import json
from backend.database import SessionLocal, Audit
from backend.seo_engine import run_engine

db = SessionLocal()
a = db.query(Audit).filter(Audit.id == 36).first()
data = json.loads(a.result_json)
print(f"Target: {data.get('target')}")
pages = data.get("pages", [])
print(f"Total pages: {len(pages)}")
for p in pages:
    print(f"  {p.get('url')} - status: {p.get('status')} word_count: {p.get('word_count')}")

payload = run_engine(data, probes=data.get("probes"), render=data.get("render"))
print("\n--- Current engine rescore on Audit 36 ---")
print("Overall:", payload["score"]["overall"])
print("Grade:", payload["score"]["grade"])
for cat in payload["categories"]:
    print(f"  {cat['name']}: {cat['score']} (weight={cat['weight']}, pts={cat['weighted_contribution']})")

by_cat = {}
for chk in payload.get("checks", []):
    by_cat.setdefault(chk["category"], []).append(chk)

for cat_slug, chks in by_cat.items():
    print(f"\n--- {cat_slug} ({len(chks)} checks) ---")
    for chk in chks:
        print(f"  {chk['id']}: status={chk['status']} earned={chk.get('earned')} - {chk.get('statement') or chk.get('name')}")



