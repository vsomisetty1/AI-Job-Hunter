-- Catalog validation: every query must return ZERO rows (exit via psql wrapper).
-- Run after migrations:  psql -f tests/sql/validate_catalog.sql
-- Each row returned is a finding: (check_name, object).

-- tables without a primary key
SELECT 'no_primary_key' AS check_name, c.relname::text AS object
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')
UNION ALL
-- foreign keys whose leading column has no index (slow joins / cascades)
SELECT 'fk_without_index', c.conrelid::regclass::text || '.' || c.conname
FROM pg_constraint c
WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
  AND NOT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
UNION ALL
-- constraints that are not validated
SELECT 'unvalidated_constraint', conrelid::regclass::text || '.' || conname
FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND NOT convalidated
UNION ALL
-- invalid indexes
SELECT 'invalid_index', indexrelid::regclass::text
FROM pg_index WHERE NOT indisvalid
UNION ALL
-- nullable timestamp audit columns / timestamptz discipline
SELECT 'timestamp_without_tz', table_name || '.' || column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'
UNION ALL
-- mutable tables (have updated_at) missing the updated_at trigger
SELECT 'missing_updated_trigger', c.table_name::text
FROM information_schema.columns c
WHERE c.table_schema = 'public' AND c.column_name = 'updated_at'
  AND NOT EXISTS (
        SELECT 1 FROM pg_trigger t
        WHERE t.tgrelid = (quote_ident(c.table_name))::regclass
          AND NOT t.tgisinternal AND t.tgname = 'trg_' || c.table_name || '_updated')
UNION ALL
-- tables without created_at (agent_runs uses started_at)
SELECT 'missing_created_at', t.table_name::text
FROM information_schema.tables t
WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
  AND t.table_name NOT IN ('alembic_version', 'agent_runs')
  AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.table_name = t.table_name AND c.column_name = 'created_at')
UNION ALL
-- naming: constraints must carry ck_/uq_/fk_ prefix; indexes ix_/uq_
SELECT 'bad_constraint_name', conrelid::regclass::text || '.' || conname
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace AND contype IN ('c', 'u', 'f')
  AND conname !~ '^(ck|uq|fk)_'
UNION ALL
SELECT 'bad_index_name', indexrelid::regclass::text
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relnamespace = 'public'::regnamespace AND NOT i.indisprimary
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)
  AND c.relname !~ '^(ix|uq)_'
UNION ALL
-- char(n) columns: bpchar vs text/varchar comparisons cannot use their indexes
SELECT 'char_n_column', table_name || '.' || column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND data_type = 'character'
UNION ALL
-- duplicate indexes (identical definition apart from name)
SELECT 'duplicate_index', string_agg(indexrelid::regclass::text, ', ')
FROM pg_index
WHERE indrelid::regclass::text !~ '^pg_'
GROUP BY indrelid, indkey::text, indclass::text, indpred::text, indexprs::text
HAVING count(*) > 1;
