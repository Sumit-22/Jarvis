-- JARVIS SQLite schema. Applied idempotently on startup. Never store secrets here.
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    canonical_intent TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    params_schema TEXT NOT NULL DEFAULT '{}',
    steps TEXT NOT NULL DEFAULT '[]',
    uses_llm_per_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS workflow_aliases (
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    alias TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alias ON workflow_aliases(alias);

CREATE TABLE IF NOT EXISTS workflow_patterns (
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    regex TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    workflow_id INTEGER REFERENCES workflows(id),
    command_text TEXT NOT NULL,
    route TEXT NOT NULL,
    status TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    plan TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS execution_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL REFERENCES executions(id),
    idx INTEGER NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    result TEXT,
    verification TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    est_cost REAL,
    created_at TEXT NOT NULL
);
