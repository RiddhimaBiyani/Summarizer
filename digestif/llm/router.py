"""Multi-tier LLM router with privacy routing, quota tracking, fallback chains, and structured output validation."""

import asyncio
import datetime
import json
import os
import random
import time
from typing import Any, Type, TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from digestif.db.repo import db
from digestif.llm.jsonfix import extract_json_from_llm_response, repair_json_text
from digestif.observability import logger
from digestif.settings import settings

T = TypeVar("T", bound=BaseModel)

# Suppress noisy LiteLLM logs
litellm.suppress_debug_info = True


class AllProvidersExhausted(Exception):
    """Raised when every provider in the fallback chain has failed or been exhausted."""

    pass


class LLMRouter:
    def __init__(self) -> None:
        self._mock_handler = None

    def set_mock_handler(self, handler) -> None:
        """Sets a mock handler for testing without network calls."""
        self._mock_handler = handler

    async def run(
        self,
        task: str,
        messages: list[dict[str, str]],
        schema: Type[T] | None = None,
        content_class: str = "public",  # "public" | "personal"
        max_tokens: int | None = None,
        item_id: int | None = None,
        timeout: float = 90.0,
    ) -> Any:
        """Executes an LLM task following fallback chains and privacy boundaries."""
        if self._mock_handler:
            return await self._mock_handler(task, messages, schema, content_class)

        # response_format={"type": "json_object"} only guarantees syntactically valid
        # JSON, not any particular shape -- models routinely return the right keys
        # with the wrong nesting (e.g. key_points as plain strings instead of
        # {point, detail, ...} objects) because they were never told the actual
        # schema, only a prose description of it. Give them the real contract.
        if schema is not None:
            messages = self._inject_schema(messages, schema)

        # 1. Resolve candidate models for task
        tasks_cfg = settings.providers_config.get("llm", {}).get("tasks", {})
        models_cfg = settings.providers_config.get("llm", {}).get("models", {})
        fallback_chain = tasks_cfg.get(task, ["gemini/flash-lite", "groq/openai/gpt-oss-120b"])

        # 2. Filter models according to Privacy Barrier
        privacy_cfg = settings.app_config.get("privacy", {})
        allow_training_for_personal = privacy_cfg.get(
            "allow_training_tiers_for_personal_content", False
        )
        allow_training_for_public = privacy_cfg.get("allow_training_tiers_for_public_content", True)
        is_personal = (content_class == "personal") or (
            task in ("relevance", "analyze_personal", "ask")
        )
        allow_training_tier = (
            allow_training_for_personal if is_personal else allow_training_for_public
        )

        eligible_models = []
        for alias in fallback_chain:
            m_info = models_cfg.get(alias, {})
            training_tier = m_info.get("training_tier", True)
            if not allow_training_tier:
                # Disallow training_tier=True or unknown
                if training_tier is True or training_tier == "unknown":
                    logger.debug(
                        "Skipping model due to training tier",
                        model=alias,
                        task=task,
                        is_personal=is_personal,
                    )
                    continue
            eligible_models.append(alias)

        if not eligible_models:
            raise AllProvidersExhausted(
                f"No eligible models available for task '{task}' with content_class='{content_class}'"
            )

        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        error_box: list[str] = []

        # 3. Iterate through fallback chain
        for alias in eligible_models:
            m_info = models_cfg.get(alias, {})
            litellm_model = m_info.get("litellm", alias)
            provider = alias.split("/")[0]

            # Check if marked exhausted for today
            if db.is_model_exhausted(today, provider, alias):
                logger.debug("Model is currently marked exhausted in quota ledger", model=alias)
                continue

            # Resolve API key
            api_key = self._resolve_api_key(provider)
            if not api_key and provider not in ("ollama", "local"):
                logger.debug("No API key configured for provider", provider=provider)
                error_box.append(f"{alias}: no API key configured for provider '{provider}'")
                continue

            # Execute attempt with retries for transient 429 RPM
            result = await self._call_model(
                alias=alias,
                provider=provider,
                litellm_model=litellm_model,
                api_key=api_key,
                task=task,
                messages=messages,
                schema=schema,
                max_tokens=max_tokens,
                item_id=item_id,
                timeout=timeout,
                error_box=error_box,
            )

            if result is not None:
                return result

        last_error = error_box[-1] if error_box else None
        raise AllProvidersExhausted(
            f"All providers exhausted for task '{task}'. Last error: {last_error}"
        )

    async def _call_model(
        self,
        alias: str,
        provider: str,
        litellm_model: str,
        api_key: str | None,
        task: str,
        messages: list[dict[str, str]],
        schema: Type[T] | None,
        max_tokens: int | None,
        item_id: int | None,
        timeout: float,
        error_box: list[str],
    ) -> Any | None:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        retries = 2

        for attempt in range(retries + 1):
            start_time = time.monotonic()
            try:
                kwargs: dict[str, Any] = {
                    "model": litellm_model,
                    "messages": messages,
                    "timeout": timeout,
                }
                if api_key:
                    kwargs["api_key"] = api_key
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                if provider == "ollama":
                    kwargs["api_base"] = settings.OLLAMA_BASE_URL
                elif provider == "cloudflare" and settings.CLOUDFLARE_ACCOUNT_ID:
                    kwargs["api_base"] = (
                        f"https://api.cloudflare.com/client/v4/accounts/"
                        f"{settings.CLOUDFLARE_ACCOUNT_ID}/ai/run"
                    )

                # Set JSON object format when schema is required
                if schema is not None:
                    kwargs["response_format"] = {"type": "json_object"}

                response = await litellm.acompletion(**kwargs)
                latency_ms = int((time.monotonic() - start_time) * 1000)

                # Extract response text & tokens
                content_text = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
                tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0

                # Record successful call
                db.record_llm_call(
                    task, provider, alias, item_id, tokens_in, tokens_out, latency_ms, ok=True
                )
                db.record_quota_usage(today, provider, alias, tokens_in, tokens_out, is_429=False)

                # Parse and validate structured schema if requested
                if schema is not None:
                    return self._parse_and_validate(content_text, schema)

                return content_text

            except litellm.RateLimitError as rle:
                latency_ms = int((time.monotonic() - start_time) * 1000)
                db.record_llm_call(
                    task, provider, alias, item_id, 0, 0, latency_ms, ok=False, error=str(rle)
                )
                db.record_quota_usage(today, provider, alias, 0, 0, is_429=True)

                err_str = str(rle).lower()
                # If daily quota limit (RPD/TPD), mark model exhausted until midnight
                if "daily" in err_str or "rpd" in err_str or "tpd" in err_str or "quota" in err_str:
                    midnight = (
                        (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
                        .replace(hour=0, minute=0, second=0)
                        .isoformat()
                    )
                    db.mark_model_exhausted(today, provider, alias, until=midnight)
                    logger.warning(
                        "Daily quota reached for model; marking exhausted until midnight",
                        model=alias,
                    )
                    error_box.append(f"{alias}: daily quota exhausted ({rle})")
                    return None

                # Transient per-minute rate limit: exponential backoff with jitter
                if attempt < retries:
                    backoff = (2**attempt) + random.uniform(0.5, 2.0)
                    logger.info(
                        "429 rate limit hit, backing off with jitter", model=alias, backoff=backoff
                    )
                    await asyncio.sleep(backoff)
                    continue
                error_box.append(f"{alias}: rate limited after {retries + 1} attempts ({rle})")
                return None

            except litellm.NotFoundError as nfe:
                # 404 or decommissioned model: disable for 24h
                tomorrow = (
                    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
                ).isoformat()
                db.mark_model_exhausted(today, provider, alias, until=tomorrow)
                logger.error(
                    "Model not found / deprecated; disabled for 24h", model=alias, error=str(nfe)
                )
                error_box.append(f"{alias}: not found / decommissioned ({nfe})")
                return None

            except Exception as e:
                latency_ms = int((time.monotonic() - start_time) * 1000)
                db.record_llm_call(
                    task, provider, alias, item_id, 0, 0, latency_ms, ok=False, error=str(e)
                )
                logger.warning(
                    "LLM call attempt failed", model=alias, attempt=attempt, error=str(e)
                )
                if attempt < retries:
                    await asyncio.sleep(1.0)
                    continue
                error_box.append(f"{alias}: {e}")
                return None

        return None

    def _inject_schema(
        self, messages: list[dict[str, str]], schema: Type[T]
    ) -> list[dict[str, str]]:
        """Returns a copy of `messages` with the target JSON schema appended to the
        system message (creating one if absent), so JSON-object mode has an actual
        contract to follow instead of just a prose description of the shape."""
        schema_note = (
            "\n\nRespond with a single JSON object that strictly matches this JSON "
            "Schema (follow field names and nesting exactly; do not flatten nested "
            f"objects into strings):\n{json.dumps(schema.model_json_schema())}"
        )
        new_messages = [dict(m) for m in messages]
        for m in new_messages:
            if m.get("role") == "system":
                m["content"] = m["content"] + schema_note
                return new_messages
        new_messages.insert(0, {"role": "system", "content": schema_note.strip()})
        return new_messages

    def _resolve_api_key(self, provider: str) -> str | None:
        if provider == "gemini":
            return settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        elif provider == "groq":
            return settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
        elif provider == "openrouter":
            return settings.OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY")
        elif provider == "mistral":
            return settings.MISTRAL_API_KEY or os.environ.get("MISTRAL_API_KEY")
        elif provider == "cloudflare":
            return settings.CLOUDFLARE_API_TOKEN or os.environ.get("CLOUDFLARE_API_TOKEN")
        return None

    def _parse_and_validate(self, text: str, schema: Type[T]) -> T:
        try:
            parsed_json = extract_json_from_llm_response(text)
            return schema.model_validate(parsed_json)
        except (ValueError, ValidationError) as e:
            logger.warning("Validation error on LLM response, attempting json repair", error=str(e))
            # Second pass: actually repair common LLM JSON mistakes (trailing commas)
            # before retrying, instead of re-parsing the identical text.
            parsed_json = extract_json_from_llm_response(repair_json_text(text))
            return schema.model_validate(parsed_json)


router = LLMRouter()
