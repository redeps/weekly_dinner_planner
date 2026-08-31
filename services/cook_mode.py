"""
Cook Mode step-splitting — turns a recipe's free-text `instructions` into
a list of display steps, split by line (see docs/PRODUCT_SPEC.md §12 and
docs/DATA_MODEL.md). No new schema: this is presentation-only, computed at
render time from the existing `recipes.instructions` column.
"""

from typing import Optional


def split_instructions_into_steps(instructions: Optional[str]) -> list[str]:
    """Split free-text instructions into steps, one per non-blank line,
    stripped of surrounding whitespace. Returns an empty list for missing
    or blank instructions."""
    if not instructions:
        return []
    return [line.strip() for line in instructions.splitlines() if line.strip()]
