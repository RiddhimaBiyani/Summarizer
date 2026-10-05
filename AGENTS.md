# Agent Guide for DIGESTIF

This project strictly adheres to the specifications in `docs/BUILD_SPEC.md`.

## Hard Rules (from Section 0)
1. **Zero recurring cost is a hard constraint.** Only use free tiers, open-source libraries, and local models. Never introduce paid dependencies.
2. **Every external provider sits behind an interface** (`LLMProvider`, `SearchProvider`, `Transcriber`, `TTSProvider`, `Channel`, `Extractor`). Swapping a provider must be a config change, not a code change.
3. **Model IDs, quotas, and provider order live in `config/providers.yaml`**, never hardcoded in code. The router must gracefully survive 404/decommissioning by falling back.
4. **Never hardcode secrets.** Read from `.env`. Ship `.env.example`.
5. **All fetched content is untrusted data** (Section 19). No LLM call that processes fetched content may have tools that take actions.
6. Keep prompts in `digestif/prompts/*.md` with a version header; never inline long prompts in Python.
7. Write tests alongside code. Extractors are tested against saved fixtures, not live sites.
8. Prefer boring, well-maintained libraries. Document any deviation from the spec in `DECISIONS.md`.
9. Target: runs on a laptop (macOS/Windows-WSL/Linux) and an Oracle Cloud Always Free ARM VM.

Maintain `PROGRESS.md` after each milestone.
