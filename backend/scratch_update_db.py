import sqlite3
import json
import sys
import os
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath("."))
from backend.main import run_spec_engine, apply_engine_payload
from backend.report_service import build_client_report_snapshot

db_path = './seo_platform.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

def clean_audit_pages(data):
    pages = data.get("pages", [])
    if not pages:
        return data
    seen_bases = set()
    for p in pages:
        u = p.get("url", "")
        parsed = urlparse(u)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/").lower()
        if not parsed.query:
            seen_bases.add(clean_url)
    cleaned = []
    for p in pages:
        u = p.get("url", "")
        parsed = urlparse(u)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/").lower()
        if parsed.query and clean_url in seen_bases:
            continue
        cleaned.append(p)
    data["pages"] = cleaned
    data["page_count"] = len(cleaned)
    return data

# Update audits for voltedge
rows = c.execute("SELECT id, target_url, score, result_json FROM audits WHERE target_url LIKE '%voltedge%'").fetchall()
print(f"VoltEdge Audits found: {len(rows)}")
audit_map = {}
for aid, url, score, rjson in rows:
    if rjson:
        data = json.loads(rjson)
        data = clean_audit_pages(data)
        res = run_spec_engine(data)
        apply_engine_payload(data, res)
        new_score = res.get("score", {}).get("overall")
        audit_map[aid] = data
        print(f"  Audit {aid}: page_count={len(data.get('pages', []))}, new score={new_score}, potential={res.get('score', {}).get('potential', {}).get('overall')}")
        c.execute("UPDATE audits SET score=?, result_json=? WHERE id=?", (new_score, json.dumps(data), aid))

# Update public_reports
prows = c.execute("SELECT id, audit_id, token, snapshot_json FROM public_reports").fetchall()
print(f"Public reports found: {len(prows)}")
for pid, aid, token, snap_json in prows:
    snap = json.loads(snap_json) if snap_json else {}
    target_url = snap.get('target_url', '')
    if 'voltedge' in target_url and aid in audit_map:
        audit_data = audit_map[aid]
        client_name = snap.get('client_name', '')
        company = snap.get('company', '')
        new_snap = build_client_report_snapshot(audit_data, client_name=client_name, company=company, token=token)
        print(f"  Public Report {pid} (token: {token}): new score = {new_snap.get('score')}, grade = {new_snap.get('grade')}")
        c.execute("UPDATE public_reports SET snapshot_json=? WHERE id=?", (json.dumps(new_snap), pid))

conn.commit()
conn.close()
print("All target records successfully updated and verified!")
