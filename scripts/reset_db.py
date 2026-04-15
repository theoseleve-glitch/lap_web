"""Reset production database — truncate all tables except alembic_version."""
import os
import psycopg2

conn = psycopg2.connect(os.environ["TELEMETRY_PG_URL"])
cur = conn.cursor()

cur.execute("SET session_replication_role = replica")

cur.execute(
    "SELECT tablename FROM pg_tables "
    "WHERE schemaname = 'public' AND tablename != 'alembic_version' "
    "ORDER BY tablename"
)
tables = [r[0] for r in cur.fetchall()]
print(f"Truncating {len(tables)} tables...")
for t in tables:
    cur.execute(f'TRUNCATE TABLE "{t}" CASCADE')
    print(f"  truncated: {t}")

cur.execute("SET session_replication_role = DEFAULT")
conn.commit()

cur.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM sessions)")
row = cur.fetchone()
print(f"Done. Users: {row[0]}, Sessions: {row[1]}")
conn.close()
