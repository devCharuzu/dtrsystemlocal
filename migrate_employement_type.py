"""
One-time migration: adds the `employment_type` column to the `employees` table.
Safe to run multiple times — skips if the column already exists.

Usage:
    python migrate_employment_type.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "form48.db"

def migrate():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH} — nothing to migrate.")
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Check if column already exists
    cur.execute("PRAGMA table_info(employees)")
    columns = [row[1] for row in cur.fetchall()]

    if "employment_type" in columns:
        print("Column `employment_type` already exists — no migration needed.")
        con.close()
        return

    print("Adding `employment_type` column (default: PERMANENT) ...")
    cur.execute(
        "ALTER TABLE employees ADD COLUMN employment_type TEXT NOT NULL DEFAULT 'PERMANENT'"
    )
    con.commit()
    print(f"Done. All existing employees set to PERMANENT.")
    con.close()

if __name__ == "__main__":
    migrate()