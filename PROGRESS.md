# Digestif Progress Tracking

## Milestones

- [x] Workspace initialization, uv project & pyproject.toml
- [x] Phase 0: Skeleton
  - [x] Configuration (`config.yaml`, `providers.yaml`, `profile.md`, `senders.yaml`, `.env.example`, `settings.py`)
  - [x] Logging & Observability (`structlog`)
  - [x] SQLite Schema with `sqlite-vec` + Repository layer (`repo.py`)
  - [x] Job Queue & APScheduler (`jobs/`)
  - [x] System Health & Diagnostics (`cli.py doctor`)
  - [x] Multi-arch Dockerfile & Docker Compose
  - [x] CI configuration (.github/workflows/ci.yml)
- [x] Phase 1: The Habit Test (MVP)
  - [x] Security (SSRF guard, untrusted content wrap)
  - [x] URL Normalization & Dedup (`normalize/`)
  - [x] Extractors: Generic Web, Substack API, Newsletter EML, Raw Text (`extract/`)
  - [x] Multi-Tier LLM Router & Quota Ledger (`llm/`)
  - [x] Privacy Boundary: personal content filter (Groq/Ollama only)
  - [x] Item Analysis & Relevance scoring (`analyze/`)
  - [x] Deterministic Number Hallucination Guard (`analyze/hallucination.py`)
  - [x] Time-budget Allocation (`digest/budget.py`)
  - [x] Section Writers & Editor Pass (`digest/writers.py`, `digest/editor.py`)
  - [x] Rendering: Jinja2 HTML, Premailer-inlined email, Telegram teaser (`digest/render.py`)
  - [x] Delivery: Telegram Out & Email Out (`deliver/`)
  - [x] Telegram Bot Poller & Commands (`capture/telegram.py`, `interaction/commands.py`)
  - [x] IMAP Poller & Forward Unwrapping (`capture/imap.py`)
  - [x] Catch-up on wake & Quiet Hours (`reliability/catchup.py`)
- [x] Parallel QA Suites
  - [x] QA 1: Unit, Fixture & Contract Suite (40+ URL test cases, budget invariants)
  - [x] QA 2: Security & Privacy Compliance Auditor (SSRF penetration, privacy lane isolation, prompt-injection defense)
  - [x] QA 3: End-to-End Simulation & Idempotency Validator (multi-source day simulation, single-digest idempotency)

