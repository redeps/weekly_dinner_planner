"""
Cook Mode step-splitting — turns a recipe's free-text `instructions` into
a list of display steps, split by line (see docs/PRODUCT_SPEC.md §12 and
docs/DATA_MODEL.md). No new schema: this is presentation-only, computed at
render time from the existing `recipes.instructions` column.

Secondary split: a newline-derived step that's too long for one glanceable
screen is further split at sentence boundaries, still purely at render
time. `SPLIT_THRESHOLD_CHARS` is an estimated proxy for "fits on a typical
mobile screen at Cook Mode's font size without scrolling" — not a measured
value; see docs/DECISIONS.md for the reasoning and why it may need
revisiting once there's real usage to check it against.
"""

import re
from typing import Optional

SPLIT_THRESHOLD_CHARS = 180

# Sentence-final punctuation followed by whitespace and a capital letter or
# an opening parenthesis - a period followed by a lowercase letter, digit,
# or nothing (end of string) is not treated as a sentence boundary, which
# already avoids most decimal-number and mid-clause false splits for free.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

# Trailing tokens that precede a "sentence-ending" period without actually
# ending the sentence (units, honorifics, and other short abbreviations
# common in recipe instructions). A split right after one of these is
# merged back into the previous piece. Deliberately a small hardcoded list,
# not a real sentence-boundary detector - see docs/DECISIONS.md (Milestone
# 7 Cook Mode step density) for why that tradeoff was made.
_ABBREVIATIONS = {
    "tbsp", "tsp", "oz", "lb", "lbs", "approx", "min", "mins", "hr", "hrs",
    "no", "etc", "e.g", "i.e", "mr", "mrs", "dr", "vs", "fl", "in", "fig",
    "gal", "pt", "qt", "sq", "st",
}


def _naive_sentences(step: str) -> list[str]:
    """Split one step into sentences, undoing false splits after a known
    abbreviation (e.g. "Add 2 tbsp. Butter..." stays one sentence)."""
    pieces = _SENTENCE_BOUNDARY_RE.split(step)
    sentences: list[str] = []
    for piece in pieces:
        if sentences:
            previous = sentences[-1]
            previous_words = previous.rstrip(".").split()
            trailing_token = previous_words[-1].lower() if previous_words else ""
            if previous.endswith(".") and trailing_token in _ABBREVIATIONS:
                sentences[-1] = f"{previous} {piece}"
                continue
        sentences.append(piece)
    return sentences


def _pack_sentences(sentences: list[str], limit: int) -> list[str]:
    """Greedily group consecutive sentences up to `limit` characters each,
    rather than one sentence per sub-step - many individual sentences are
    short enough that pairing them still fits one glanceable screen."""
    groups: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= limit:
            current = f"{current} {sentence}"
        else:
            groups.append(current)
            current = sentence
    if current:
        groups.append(current)
    return groups


def _split_step_for_display(step: str, limit: int = SPLIT_THRESHOLD_CHARS) -> list[str]:
    """A single newline-derived step, expanded into one or more display
    sub-steps. Steps at or under `limit` pass through unchanged. Over the
    limit, split into sentences and repacked; a step that's one long
    connected sentence with no sentence boundary at all is left as a
    single (long) sub-step rather than chopped mid-sentence."""
    if len(step) <= limit:
        return [step]
    sentences = _naive_sentences(step)
    if len(sentences) <= 1:
        return [step]
    return _pack_sentences(sentences, limit)


def split_instructions_into_steps(instructions: Optional[str]) -> list[str]:
    """Split free-text instructions into display steps: one per non-blank
    line, further split at sentence boundaries when a line is too long for
    one glanceable screen (see `SPLIT_THRESHOLD_CHARS`). Returns an empty
    list for missing or blank instructions."""
    if not instructions:
        return []
    lines = [line.strip() for line in instructions.splitlines() if line.strip()]
    steps: list[str] = []
    for line in lines:
        steps.extend(_split_step_for_display(line))
    return steps
