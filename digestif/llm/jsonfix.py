"""JSON extractor and repair utilities for LLM responses."""

import json
import re
from typing import Any


def extract_json_from_llm_response(text: str) -> dict[str, Any]:
    """Extracts JSON object from text that may contain markdown fences or surrounding chatter."""
    text = text.strip()

    # Try direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Try fenced code block ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        snippet = match.group(1).strip()
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # Try searching for the outermost { ... }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        snippet = text[first_brace : last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    raise ValueError(f"Could not parse valid JSON object from LLM response:\n{text[:300]}...")


def repair_json_text(text: str) -> str:
    """Fixes common LLM JSON formatting mistakes: trailing commas before `}`/`]`."""
    return re.sub(r",\s*([}\]])", r"\1", text)
