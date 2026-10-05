"""Deterministic number and fact hallucination guard."""

import re

# Regex to capture numbers, currency amounts, percentages, and metrics
NUMBER_REGEX = re.compile(
    r"(?:[\$₹€£]\s*[\d,.]+(?:\s*(?:crore|lakh|million|billion|trillion|mn|bn|k))?|"
    r"[\d,.]+\s*(?:%|percent|crore|lakh|million|billion|trillion|mn|bn|k)?\b)",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> set[str]:
    """Extracts normalized numbers, percentages, and financial quantities from text."""
    if not text:
        return set()
    raw_matches = NUMBER_REGEX.findall(text)
    normalized = set()
    for m in raw_matches:
        cleaned = re.sub(r"[\s,]", "", m.lower())
        # Strip trailing decimal zeros (e.g. 5.0 -> 5)
        cleaned = re.sub(r"\.0(?=\D|$)", "", cleaned)
        if any(ch.isdigit() for ch in cleaned):
            normalized.add(cleaned)
    return normalized


def verify_numbers_against_source(generated_text: str, source_text: str) -> tuple[bool, set[str]]:
    """Verifies that all numbers present in generated_text also exist in source_text.

    Returns (is_clean, unverified_numbers).
    """
    gen_numbers = extract_numbers(generated_text)
    src_numbers = extract_numbers(source_text)

    # Allow common small numbers/indexes (1, 2, 3, 4, 5, 10, 100)
    allowed_common = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "100"}

    # Compare by full digit sequence (not substring containment) so a short number
    # like "45" doesn't get falsely "verified" just because it appears inside an
    # unrelated longer source number like "$145million".
    src_digit_set = {re.sub(r"\D", "", s) for s in src_numbers}

    unverified = set()
    for num in gen_numbers:
        if num in allowed_common:
            continue
        if num not in src_numbers:
            digits = re.sub(r"\D", "", num)
            if digits and digits not in src_digit_set:
                unverified.add(num)

    return (len(unverified) == 0, unverified)
