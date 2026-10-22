"""Text helpers shared by query resolution and its sibling parsers."""

from __future__ import annotations

import re
import unicodedata


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()
