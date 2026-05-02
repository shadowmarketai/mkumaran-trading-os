"""Quick diagnostic: what's in options_chain_cache?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_server.db import SessionLocal
from sqlalchemy import text

s = SessionLocal()

print("=== Underlyings in options_chain_cache ===")
q1 = text("""
    SELECT underlying,
           COUNT(*) AS rows,
           COUNT(DISTINCT expiry_date) AS expiries,
           MIN(expiry_date) AS earliest,
           MAX(expiry_date) AS latest
    FROM options_chain_cache
    GROUP BY underlying
    ORDER BY underlying
""")
for r in s.execute(q1).fetchall():
    print(f"  {r.underlying:<12} rows={r.rows:>8,}  expiries={r.expiries:>4}  "
          f"{r.earliest} → {r.latest}")

print()
print("=== NIFTY monthly breakdown ===")
q2 = text("""
    SELECT DATE_TRUNC('month', expiry_date) AS month,
           COUNT(DISTINCT expiry_date) AS expiries,
           COUNT(DISTINCT strike)      AS strikes,
           COUNT(*)                    AS rows
    FROM options_chain_cache
    WHERE underlying = 'NIFTY'
    GROUP BY 1
    ORDER BY 1
""")
rows = s.execute(q2).fetchall()
if not rows:
    print("  (no NIFTY data)")
else:
    for r in rows:
        print(f"  {str(r.month)[:7]}  expiries={r.expiries}  strikes={r.strikes:>4}  rows={r.rows:>7,}")

s.close()
