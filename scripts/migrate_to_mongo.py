import os
import sqlite3
import pymongo
from datetime import datetime

MONGO_URI = os.getenv("DATABASE_URL") or os.getenv("MONGO_URI")
if not MONGO_URI or not (MONGO_URI.startswith("mongodb://") or MONGO_URI.startswith("mongodb+srv://")):
    raise ValueError("Set DATABASE_URL or MONGO_URI environment variable with a valid MongoDB URI before running migration.")

client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000, socketTimeoutMS=30000)
db = client["seo_platform"]

con = sqlite3.connect("seo_platform.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

def parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        v = v.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                pass
    return v

date_cols = {
    "created_at", "updated_at", "completed_at", "published_at",
    "disabled_at", "last_login_at", "expires_at", "used_at",
    "last_run_at", "next_run_at"
}

tables = [
    "admin_users", "clients", "websites", "audits", "public_reports",
    "team_invitations", "admin_sessions", "activity_logs", "lead_notes",
    "seo_leads", "public_scans", "scheduled_audits"
]

for table in tables:
    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = [dict(r) for r in cur.fetchall()]
        col = db[table]
        col.delete_many({})
        max_id = 0
        print(f"Migrating {table} ({len(rows)} records)...")
        for idx, row in enumerate(rows):
            if "id" in row and row["id"] is not None:
                if row["id"] > max_id:
                    max_id = row["id"]
            for c in date_cols:
                if c in row and row[c]:
                    row[c] = parse_dt(row[c])
            col.replace_one({"id": row["id"]}, row, upsert=True)
            if (idx + 1) % 10 == 0 or (idx + 1) == len(rows):
                print(f"  {table}: {idx + 1}/{len(rows)} done")
        if max_id > 0:
            db["_counters"].update_one({"_id": table}, {"$set": {"seq": max_id}}, upsert=True)
        print(f"Done {table} (max_id={max_id})")
    except Exception as e:
        print(f"Error migrating {table}: {e}")

print("All migrations complete!")

