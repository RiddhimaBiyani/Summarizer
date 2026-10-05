# Architectural Decisions Log (DECISIONS.md)

### ADR 001: SQLite WAL mode with `sqlite-vec`
- **Context:** Digestif is a single-user system requiring simple backups and zero operational overhead.
- **Decision:** Use SQLite with Write-Ahead Logging (WAL) and `sqlite-vec` extension for vector operations.
- **Consequences:** Single-file database, concurrent reads during writes, native vector similarity matching without external vector DBs.

### ADR 002: Dual Routing and Privacy Barrier for LLM Operations
- **Context:** Gemini API free-tier terms allow submitted data to be used for model training and reviewed by humans.
- **Decision:** Partition all LLM tasks into `content_class="public"` (articles, public newsletters) and `content_class="personal"` (user notes, voice notes, user profile interests, reflection notes, and `/ask` queries).
- **Consequences:** Personal content strictly avoids models tagged `training_tier: true` or `training_tier: unknown`. Personal tasks route to Groq free models, Cloudflare Workers AI, or local Ollama.

### ADR 003: Deterministic Budget Allocation
- **Context:** LLMs struggle to consistently hit exact word count targets or allocate reading time proportionally across disparate items.
- **Decision:** Budget allocation is calculated mathematically in Python using reading WPM, priority scores, and logarithmic length scaling before prompting section writers.
- **Consequences:** Predictable total reading time (±15% target), guaranteed minimum length per item, and deterministic demotion to quick-hits on overflow.
