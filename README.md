# DIGESTIF — Zero-Cost Personal Content Digest

A single-user, self-hosted digest engine that converts daily saved content across Telegram and email newsletters into an intelligent, time-budgeted nightly digest with ₹0 recurring cost.

## Features
- **Capture**: Telegram Bot (long polling) + dedicated Gmail inbox (IMAP)
- **Zero-Cost LLM Stack**: Multi-provider fallback router (Gemini Flash-Lite/Flash, Groq 120b/20b, local Ollama)
- **Privacy Guard**: Personal content (profile, user notes, private thoughts) never hits training-tier models
- **Deterministic Budgeting**: Exact time-budgeted reading lengths (15/20/30 min @ 230 wpm)
- **High-Quality Delivery**: Mobile-first responsive HTML, premailer-inlined emails, and interactive Telegram teaser
- **Anti-Hallucination Guard**: Deterministic number verification between summaries and sources

## Quick Start
```bash
# Setup virtual environment
uv venv .venv
# On Windows: .venv\Scripts\activate
# On Linux/macOS: source .venv/bin/activate
uv pip install -e ".[dev]"

# Check environment & providers
digestif doctor

# Run service
digestif run
```

## Security & Privacy Notice
Digests are strictly personal. Never ingest work-restricted or PHI/PII data. All fetched web content is isolated in `<untrusted_content>` tags.
