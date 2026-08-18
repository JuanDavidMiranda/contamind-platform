"""Create a test user for local development."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from app.shared.security import hash_password

conn = psycopg2.connect(
    host="localhost", port=5433,
    user="contamind", password="contamind",
    dbname="contamind",
)
conn.autocommit = True
cur = conn.cursor()

pw_hash = hash_password("Test1234")

cur.execute(
    "INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
    "VALUES (%s, %s, %s, %s) RETURNING id, email, full_name, is_platform_admin",
    ("admin@contamind.test", "Admin ContaMind", pw_hash, True),
)
user = cur.fetchone()
print(f"User created: id={user[0]}, email={user[1]}, name={user[2]}, admin={user[3]}")

conn.close()
