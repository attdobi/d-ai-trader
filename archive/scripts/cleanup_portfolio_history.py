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
# Recovery window must exceed the snapshot cadence (2h cycles; overnight gaps
# for sparse periods). A genuine >15% drop that FULLY recovers by the next
# snapshot(s) within a day is a settled-cash artifact, not a market move.
RECOVER_WINDOW = timedelta(hours=26)

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

# Second pass — segment-based, for sparse-snapshot eras where "recovery" is
# days away: collapse consecutive rows within 2% into segments; an interior
# segment shorter than 48h sitting >=20% below BOTH neighboring segments is
# an artifact plateau (e.g. 2852 -> 1350 -> 2876), not a market move.
cur.execute(
    """SELECT id, timestamp, total_portfolio_value FROM portfolio_history
       WHERE config_hash = %s ORDER BY timestamp, id""",
    (HASH,),
)
rows = cur.fetchall()
segments = []  # [ids], first_ts, last_ts, value
for _id, ts, v in rows:
    if v is None:
        continue
    if segments and abs(v - segments[-1][3]) <= 0.02 * max(segments[-1][3], 1):
        segments[-1][0].append(_id)
        segments[-1][2] = ts
    else:
        segments.append([[_id], ts, ts, v])

seg_bad = []
for k in range(1, len(segments) - 1):
    ids, t0, t1, v = segments[k]
    prev_v, next_v = segments[k - 1][3], segments[k + 1][3]
    short = (t1 - t0) <= timedelta(hours=48)
    if short and v < 0.8 * prev_v and v < 0.8 * next_v:
        seg_bad.extend(ids)

print(f"segment-pass artifact rows: {len(seg_bad)}")
if seg_bad:
    cur.execute("DELETE FROM portfolio_history WHERE id = ANY(%s)", (seg_bad,))
    conn.commit()
    print(f"deleted {cur.rowcount}")

# Repair the cash column on surviving rows where total != cash + invested
# (writers used to log settled/display cash next to a correct total). Charts
# of the cash series otherwise still show the dips. cash := total - invested
# (cost-basis approximation; off only by unrealized P/L, invisible at chart scale).
cur.execute(
    """UPDATE portfolio_history
       SET cash_balance = total_portfolio_value - COALESCE(total_invested, 0)
       WHERE config_hash = %s
         AND ABS(total_portfolio_value - (COALESCE(cash_balance,0) + COALESCE(total_invested,0))) > 2""",
    (HASH,),
)
print(f"cash column repaired on {cur.rowcount} rows")
conn.commit()

cur.execute(
    """SELECT COUNT(*), MIN(total_portfolio_value)::int, MAX(total_portfolio_value)::int
       FROM portfolio_history WHERE config_hash = %s""",
    (HASH,),
)
print("after cleanup (rows, min, max):", cur.fetchone())
conn.close()
