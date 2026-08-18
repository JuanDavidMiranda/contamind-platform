"""Create a test tenant, company and membership for local development."""
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

# Get user id
cur.execute("SELECT id FROM users WHERE email = %s", ("admin@contamind.test",))
user_id = cur.fetchone()[0]
print(f"User id: {user_id}")

# Create tenant
cur.execute(
    "INSERT INTO tenants (id, name, country_code) "
    "VALUES (gen_random_uuid()::text, %s, %s) RETURNING id, name",
    ("ContaMind Demo", "CO"),
)
tenant_id, tenant_name = cur.fetchone()
print(f"Tenant: id={tenant_id}, name={tenant_name}")

# Create company
cur.execute(
    "INSERT INTO companies (id, tenant_id, name, functional_currency, status) "
    "VALUES (gen_random_uuid()::text, %s, %s, %s, 'active') RETURNING id, name",
    (tenant_id, "Empresa Demo S.A.S.", "COP"),
)
company_id, company_name = cur.fetchone()
print(f"Company: id={company_id}, name={company_name}")

# Create tenant membership (owner)
cur.execute(
    "INSERT INTO tenant_memberships (user_id, tenant_id, role) "
    "VALUES (%s, %s, 'owner')",
    (user_id, tenant_id),
)
print("Tenant membership: owner")

# Create company membership (owner)
cur.execute(
    "INSERT INTO company_memberships (user_id, company_id, role) "
    "VALUES (%s, %s, 'owner')",
    (user_id, company_id),
)
print("Company membership: owner")

print(f"\nDone! Company ID for API calls: {company_id}")
conn.close()
