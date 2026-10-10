"""
utils.py
--------
Shared utility helpers used across the Gee-Luma application.
"""

import re
import unicodedata
import warnings


# ---------------------------------------------------------------------------
# CrewAI / warnings compatibility shim
# ---------------------------------------------------------------------------

def _make_warn_skip_file_prefixes_compatible(warn_func):
    """
    Some dependencies call warnings.warn(..., skip_file_prefixes=...) while
    CrewAI 1.13.0 installs a warning wrapper that does not accept that keyword.
    This shim drops the unsupported kwarg before forwarding.
    """
    def _compatible_warn(message, category=None, stacklevel=1, source=None, **kwargs):
        kwargs.pop("skip_file_prefixes", None)
        return warn_func(message, category=category, stacklevel=stacklevel, source=source)
    return _compatible_warn


warnings.warn = _make_warn_skip_file_prefixes_compatible(warnings.warn)

from crewai import Agent, Task, Crew, LLM  # noqa: E402  (must come after shim)

warnings.warn = _make_warn_skip_file_prefixes_compatible(warnings.warn)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def ascii_label(value) -> str:
    """Return clean English/ASCII text suitable for map titles and file names."""
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    replacements = {"->": " to ", "--": "-", "degdeg": "deg"}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = re.sub(r"[^A-Za-z0-9 .,:;_()\[\]/+%&=<>|\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
