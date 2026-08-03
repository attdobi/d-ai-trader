"""One-off: remove transient V-dip artifacts from portfolio_history.

A dip = value falls >15% below the running reference and RECOVERS to >=85%
of that reference within 2 hours. Those rows were settled-cash/partial-state
snapshots, not market moves. Genuine level changes (no recovery) are kept.
Backup exists in portfolio_history_backup_20260803.
"""
import psycopg2
from datetime import timedelta

HASH = "9ea09b9as"
DROP = 0.85          # below 85% of reference = dip candidate
RECOVER_WINDOW = timedelta(hours=2)

conn = psycopg2.connect(dbname="adobi")
cur = conn.cursor()
cur.execute(
    """SELECT id, timestamp, total_portfolio_value FROM portfolio_history
       WHERE config_hash = %s ORDER BY timestamp, id""",
    (HASH,),
)
rows = cur.fetchall()
print(f"loaded {len(rows)} rows")

bad_ids = []
i = 1
ref = rows[0][2] if rows else None
while i < len(rows):
    _id, ts, v = rows[i]
    if ref and v is not None and v < DROP * ref:
        # candidate dip — scan ahead for recovery within the window
        j = i + 1
        recovered_at = None
        while j < len(rows) and rows[j][1] - ts <= RECOVER_WINDOW:
            if rows[j][2] is not None and rows[j][2] >= DROP * ref:
                recovered_at = j
                break
            j += 1
        if recovered_at is not None:
            bad_ids.extend(r[0] for r in rows[i:recovered_at])
            i = recovered_at
            ref = rows[i][2]
            continue
        # no recovery: genuine level change — accept it
    ref = v if v is not None else ref
    i += 1

print(f"artifact rows to delete: {len(bad_ids)}")
if bad_ids:
    cur.execute("DELETE FROM portfolio_history WHERE id = ANY(%s)", (bad_ids,))
    conn.commit()
    print(f"deleted {cur.rowcount}")

cur.execute(
    """SELECT COUNT(*), MIN(total_portfolio_value)::int, MAX(total_portfolio_value)::int
       FROM portfolio_history WHERE config_hash = %s""",
    (HASH,),
)
print("after cleanup (rows, min, max):", cur.fetchone())
conn.close()
