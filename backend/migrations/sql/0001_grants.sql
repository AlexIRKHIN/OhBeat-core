-- Privileges of the application role, taken verbatim from the header of
-- 05_Database/schema.sql. The role ohbeat_app itself is created by
-- infra/postgres/init-roles.sh (ASSUMPTION: GAP-5).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ohbeat_app;
REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_log FROM ohbeat_app;
