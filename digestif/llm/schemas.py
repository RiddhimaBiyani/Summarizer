"""Pydantic schemas for structured LLM task outputs."""

from typing import Literal

from pydantic import BaseModel, Field


class KeyPoint(BaseModel):
    point: str
    detail: str
    evidence: str = ""
    evidence_type: Literal["data", "example", "expert_claim", "reasoning", "anecdote", "none"] = (
        "none"
    )


class Fact(BaseModel):
    fact: str
    context: str = ""
    appears_verbatim_in_source: bool = True


class Framework(BaseModel):
    name: str
    explanation: str


class ItemAnalysis(BaseModel):
    title: str
    author: str = ""
    content_kind: Literal[
        "essay",
        "news",
        "analysis",
        "opinion",
        "tutorial",
        "research",
        "data_report",
        "thread",
        "interview",
        "announcement",
        "promotional",
        "entertainment",
        "other",
    ] = "essay"
    one_liner: str
    what_it_is: str
    core_thesis: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    numbers_and_facts: list[Fact] = Field(default_factory=list)
    frameworks: list[Framework] = Field(default_factory=list)
    what_you_can_learn: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    weaknesses_or_open_questions: list[str] = Field(default_factory=list)
    claims_to_verify: list[str] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    time_sensitivity: Literal["evergreen", "months", "weeks", "days"] = "evergreen"
    substance: int = 5
    verdict: Literal["read_original", "summary_enough", "skim", "skip"] = "summary_enough"
    verdict_reason: str = ""
    notable_quote: str = ""


class RelevanceResult(BaseModel):
    relevance: int = 5
    why_it_matters_to_you: str = ""
    connects_to_profile: list[str] = Field(default_factory=list)


class ThemeSynthesis(BaseModel):
    name: str
    item_ids: list[int] = Field(default_factory=list)
    synthesis: str = ""
    tension: str = ""


class EditorPassResult(BaseModel):
    headline: str
    top_three: list[str] = Field(default_factory=list)
    themes: list[ThemeSynthesis] = Field(default_factory=list)
    reading_order: list[int] = Field(default_factory=list)
    reflection_prompt: str = ""


class IntentResult(BaseModel):
    intent_type: Literal["note", "command", "question"] = "note"
    command_name: str | None = None
    args: str | None = None
    explanation: str = ""
