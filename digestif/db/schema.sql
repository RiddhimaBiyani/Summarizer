-- Digestif SQLite Schema v1.0

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,              -- telegram | email | cli | whatsapp
  external_id TEXT NOT NULL,          -- telegram update_id / message_id, email Message-ID
  received_at TEXT NOT NULL,          -- ISO8601 UTC
  raw_json TEXT NOT NULL,             -- full raw payload (email: path to .eml)
  UNIQUE(channel, external_id)        -- idempotency
);

CREATE TABLE IF NOT EXISTS digests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  digest_date TEXT UNIQUE,
  kind TEXT DEFAULT 'daily',          -- daily | weekly | catchup
  budget_minutes INTEGER,
  status TEXT,                        -- building | ready | delivered | failed
  plan_json TEXT,
  content_json TEXT,
  html_path TEXT,
  email_html_path TEXT,
  audio_path TEXT,
  word_count INTEGER,
  est_minutes REAL,
  delivered_at TEXT,
  opened_at TEXT,
  done_at TEXT
);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id INTEGER REFERENCES captures(id),
  parent_item_id INTEGER REFERENCES items(id),
  source_type TEXT NOT NULL,          -- web|substack|newsletter|x|instagram|youtube|pdf|image|voice_note|text|linkedin
  url TEXT,
  canonical_url TEXT,
  url_hash TEXT,
  title TEXT,
  author TEXT,
  publisher TEXT,
  published_at TEXT,
  user_note TEXT,
  status TEXT NOT NULL,               -- received|extracting|extracted|analyzing|analyzed|enriching|ready|needs_user|failed|archived
  failure_reason TEXT,
  word_count INTEGER,
  media_seconds INTEGER,
  original_minutes REAL,
  language TEXT,
  content_hash TEXT,
  pinned INTEGER DEFAULT 0,
  skipped INTEGER DEFAULT 0,
  priority REAL DEFAULT 0.0,
  digested_in INTEGER REFERENCES digests(id),
  carryover_count INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_urlhash ON items(url_hash);
CREATE INDEX IF NOT EXISTS idx_items_digested_in ON items(digested_in);

CREATE TABLE IF NOT EXISTS item_content (
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  text_md TEXT,
  transcript TEXT,
  ocr_text TEXT,
  media_json TEXT,
  extraction_method TEXT,
  extraction_meta TEXT
);

CREATE TABLE IF NOT EXISTS item_analysis (
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  model TEXT,
  prompt_version TEXT,
  analysis_json TEXT NOT NULL,
  substance REAL,
  relevance REAL,
  novelty REAL,
  verdict TEXT,                       -- read_original|summary_enough|skim|skip
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrichment_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  url TEXT,
  title TEXT,
  publisher TEXT,
  published_at TEXT,
  relation TEXT,
  credibility REAL,
  summary TEXT,
  retrieved_at TEXT,
  provider TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER,
  digest_id INTEGER,
  kind TEXT,                          -- up|down|more_like|less_like|deep|quiz_correct|quiz_wrong|read_original
  payload TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS takeaways (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  next_due TEXT NOT NULL,
  interval_days INTEGER DEFAULT 1,
  ease REAL DEFAULT 2.3
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                 -- extract|analyze|relevance|enrich|build_digest|deliver_digest|imap_poll
  item_id INTEGER,
  payload TEXT,
  status TEXT NOT NULL,               -- queued|running|completed|failed
  attempts INTEGER DEFAULT 0,
  run_after TEXT NOT NULL,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_run ON jobs(status, run_after);

CREATE TABLE IF NOT EXISTS quota_ledger (
  day TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  requests INTEGER DEFAULT 0,
  tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  errors_429 INTEGER DEFAULT 0,
  exhausted_until TEXT,
  PRIMARY KEY(day, provider, model)
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  item_id INTEGER,
  tokens_in INTEGER,
  tokens_out INTEGER,
  latency_ms INTEGER,
  ok INTEGER NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS newsletter_senders (
  address TEXT PRIMARY KEY,
  name TEXT,
  shape TEXT DEFAULT 'single_essay',   -- single_essay|multi_story|link_roundup|unknown
  trust REAL DEFAULT 0.6,
  auto_ingest INTEGER DEFAULT 1,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
