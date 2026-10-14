-- Read-only database login for viewing data (pgweb, TablePlus). It can SELECT every table, now and
-- in future migrations, and nothing else: no INSERT, UPDATE, DELETE or DDL.
--   docker compose exec -T db psql -U cadastro -d cadastro -v pw="$DB_READONLY_PASSWORD" < deploy/readonly-role.sql
SELECT format('CREATE ROLE leitura LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leitura') \gexec
SELECT format('ALTER ROLE leitura LOGIN PASSWORD %L', :'pw') \gexec
ALTER ROLE leitura SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE cadastro TO leitura;
GRANT USAGE ON SCHEMA public TO leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO leitura;
ALTER DEFAULT PRIVILEGES FOR ROLE cadastro IN SCHEMA public GRANT SELECT ON TABLES TO leitura;
-- password hashes and live sessions are not for browsing
REVOKE SELECT ON users, user_sessions FROM leitura;
GRANT SELECT (id, email, name, role, is_active, created_at, last_login_at, deactivated_at) ON users TO leitura;
