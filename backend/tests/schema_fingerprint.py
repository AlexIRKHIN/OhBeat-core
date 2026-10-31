"""A comparable description of a database schema built from the PostgreSQL catalog:
columns, constraints, indexes, sequences and privileges of ohbeat_app."""

from sqlalchemy import Connection, text

EXCLUDED_TABLES = ("alembic_version",)

QUERIES = {
    "columns": """
        SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision,
               numeric_scale, is_nullable, column_default, is_identity, identity_generation
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name <> ALL(:excluded)
        ORDER BY table_name, column_name
    """,
    "constraints": """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid), convalidated
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND conrelid::regclass::text <> ALL(:excluded)
        ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename <> ALL(:excluded)
        ORDER BY 1, 2
    """,
    "sequences": """
        SELECT sequence_name, data_type, start_value, increment
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
        ORDER BY 1
    """,
    "app_privileges": """
        SELECT table_name, privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee = 'ohbeat_app' AND table_name <> ALL(:excluded)
        ORDER BY 1, 2
    """,
}


def fingerprint(conn: Connection) -> dict[str, list[tuple]]:
    params = {"excluded": list(EXCLUDED_TABLES)}
    return {name: [tuple(row) for row in conn.execute(text(sql), params)] for name, sql in QUERIES.items()}
