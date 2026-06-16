import re

with open('db/schema.sql', 'r') as f:
    sql = f.read()

# Add tenant_id to tables
tables = ['loan_applications', 'features', 'feature_read_audit', 'model_predictions', 'audit_log', 'model_registry']

for table in tables:
    # Add tenant_id after CREATE TABLE table (
    sql = re.sub(
        rf"CREATE TABLE IF NOT EXISTS {table} \(\n",
        f"CREATE TABLE IF NOT EXISTS {table} (\n    tenant_id               VARCHAR(50)     NOT NULL,\n",
        sql
    )

# Add RLS policies
rls_sql = """
-- =============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =============================================================================

"""
for table in tables:
    rls_sql += f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;

CREATE POLICY {table}_isolation_policy ON {table}
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY {table}_admin_bypass ON {table}
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');
"""

sql += rls_sql

with open('db/schema.sql', 'w') as f:
    f.write(sql)

print("Schema updated successfully")
