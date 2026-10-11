"""
time_series.py
--------------
Splits a requested period into the periods of a multi-map figure: one map per
month, season or year, or one per calendar month / season averaged over
several years (a climatology), or a list of periods the user named.

Nothing here touches Earth Engine: it only works out which dates belong to
which map and how the figure and its maps are worded.

A panel is {"label": str, "ranges": [(start, end), ...]} with ISO dates and
exclusive ends, ready for `filterDate`. Ordinary panels have one range; a
climatology panel has one per year.

Public API:
  normalise_series(value)                    -> series kind or None
  infer_series_from_prompt(prompt)           -> series kind or None
  build_panels(kind, date_start, date_end, custom, today) -> list of panels
  series_title(kind, reducer, title_label, plain)         -> figure title
  series_subtitle(kind, panels)                           -> line under the title
  series_processing(kind, reducer, n_images, plain)       -> credit-block wording
"""

from __future__ import annotations

import re
from datetime import date, timedelta

SERIES_KINDS = ("monthly", "seasonal", "annual", "monthly_climatology", "seasonal_climatology", "custom")
CLIMATOLOGIES = ("monthly_climatology", "seasonal_climatology")
# More maps than this are too small to read on one page.
MAX_PANELS = 36

_SERIES_ALIASES = {
    "month": "monthly", "months": "monthly", "by_month": "monthly",
    "season": "seasonal", "seasons": "seasonal", "quarterly": "seasonal",
    "year": "annual", "years": "annual", "yearly": "annual", "annually": "annual",
    "monthly_climatology": "monthly_climatology", "month_climatology": "monthly_climatology",
    "climatology": "monthly_climatology", "monthly_normals": "monthly_climatology",
    "seasonal_climatology": "seasonal_climatology", "season_climatology": "seasonal_climatology",
    "panels": "custom", "comparison": "custom", "compare": "custom",
}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
# Meteorological seasons, named by their months so the labels are right in
# both hemispheres and in the tropics. December opens the first one.
_SEASON_STARTS = (12, 3, 6, 9)
_SEASON_NAMES = {12: "Dec-Feb", 3: "Mar-May", 6: "Jun-Aug", 9: "Sep-Nov"}
_UNIT_WORD = {"monthly": "month", "seasonal": "season", "annual": "year",
              "monthly_climatology": "calendar month", "seasonal_climatology": "season"}
_STAT_WORD = {"sum": "total", "mean": "mean", "median": "median", "max": "maximum", "min": "minimum"}


def normalise_series(value) -> str | None:
    """The series kind the agent named, or None for a single map."""
    key = re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())
    key = _SERIES_ALIASES.get(key, key)
    return key if key in SERIES_KINDS else None


def infer_series_from_prompt(prompt: str) -> str | None:
    """
    Safety net for when the agent leaves the series out: recognises only
    requests that plainly ask for several maps of a named unit ("monthly ...
    maps", "a map for each year"). Anything subtler is left to the agent.
    """
    text = prompt.lower()
    several = r"\b(maps|panels|each|every|per|by|month[- ]by[- ]month|year[- ]by[- ]year)\b"
    if not re.search(several, text):
        return None
    if re.search(r"\b(monthly|month[- ]by[- ]month|(each|every|per|by) (calendar )?month)\b", text):
        return "monthly"
    if re.search(r"\b(seasonal|(each|every|per|by) season)\b", text):
        return "seasonal"
    if re.search(r"\b(annual|yearly|year[- ]by[- ]year|(each|every|per|by) year)\b", text):
        return "annual"
    return None


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _units(step_months: int, first: date, start: date, end: date) -> list[tuple[date, date]]:
    """
    Whole calendar units (months, seasons or years) for the span start..end
    (end exclusive). A unit counts when the span covers at least half of it,
    and is then used in full: a map of "March" is always the whole of March,
    and a period that only clips a unit does not get a map of it.
    """
    units, unit_start = [], first
    while unit_start < end:
        unit_end = _add_months(unit_start, step_months)
        overlap = (min(unit_end, end) - max(unit_start, start)).days
        if overlap > 0:
            units.append((unit_start, unit_end, overlap / (unit_end - unit_start).days))
        unit_start = unit_end
    covered = [(a, b) for a, b, share in units if share >= 0.5]
    # A span shorter than half a unit still gets the unit it mostly lies in.
    return covered or [max(units, key=lambda u: u[2])[:2]] if units else []


def _season_first(start: date) -> date:
    """Start of the season containing `start`."""
    month = max(m for m in (3, 6, 9, 12) if m <= start.month) if start.month >= 3 else 12
    return date(start.year - (1 if start.month < 3 else 0), month, 1)


def _season_label(unit_start: date) -> str:
    if unit_start.month == 12:
        return f"Dec-Feb {unit_start.year}/{(unit_start.year + 1) % 100:02d}"
    return f"{_SEASON_NAMES[unit_start.month]} {unit_start.year}"


def build_panels(kind: str, date_start: str, date_end: str, custom: list | None = None,
                 today: date | None = None) -> list[dict]:
    """
    The maps of a series, in reading order.

    date_start / date_end: the whole requested span, both days included.
    custom: for kind "custom", [{"label", "date_start", "date_end"}, ...].
    Periods that have not begun yet are left out, and one still running ends
    today (its panel carries "partial": True).
    """
    today = today or date.today()
    last_day = today + timedelta(days=1)

    def _clip(ranges):
        kept = [(a, min(b, last_day)) for a, b in ranges if a < last_day]
        return kept, any(b > last_day for _a, b in ranges if _a < last_day)

    def _panel(label, ranges):
        kept, partial = _clip(ranges)
        if not kept:
            return None
        panel = {"label": label, "ranges": [(a.isoformat(), b.isoformat()) for a, b in kept]}
        if partial:
            panel["partial"] = True
        return panel

    panels = []
    if kind == "custom":
        for item in custom or []:
            try:
                a = date.fromisoformat(str(item["date_start"]).strip())
                b = date.fromisoformat(str(item["date_end"]).strip()) + timedelta(days=1)
            except Exception:
                continue
            if b <= a:
                continue
            label = str(item.get("label") or "").strip() or f"{a.isoformat()} to {(b - timedelta(days=1)).isoformat()}"
            panels.append(_panel(label, [(a, b)]))
        return [p for p in panels if p]

    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_end) + timedelta(days=1)
    if end <= start:
        return []

    if kind in ("monthly", "monthly_climatology"):
        units = _units(1, date(start.year, start.month, 1), start, end)
    elif kind in ("seasonal", "seasonal_climatology"):
        units = _units(3, _season_first(start), start, end)
    else:
        units = _units(12, date(start.year, 1, 1), start, end)

    if kind == "monthly":
        one_year = len({a.year for a, _b in units}) == 1
        panels = [_panel(_MONTHS[a.month - 1] if one_year else f"{_MONTHS[a.month - 1][:3]} {a.year}", [(a, b)])
                  for a, b in units]
    elif kind == "seasonal":
        panels = [_panel(_season_label(a), [(a, b)]) for a, b in units]
    elif kind == "annual":
        panels = [_panel(str(a.year), [(a, b)]) for a, b in units]
    elif kind == "monthly_climatology":
        panels = [_panel(_MONTHS[m - 1], [u for u in units if u[0].month == m]) for m in range(1, 13)]
    elif kind == "seasonal_climatology":
        panels = [_panel(_SEASON_NAMES[m], [u for u in units if u[0].month == m]) for m in _SEASON_STARTS]
    return [p for p in panels if p]


def _lower_first(text: str) -> str:
    """Lower-case the first letter of a phrase, leaving acronyms (NDVI, NO2) alone."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def series_title(kind: str, reducer: str, title_label: str, plain: bool = False) -> str:
    """
    Figure title that says what each map is: a total, an average, or a
    multi-year average of totals. `plain` is for maps with no single value to
    aggregate (colour composites, classes).
    """
    subject = _lower_first(title_label)
    stat = "" if plain else _STAT_WORD.get(reducer, "")
    unit = {"monthly": "Monthly", "seasonal": "Seasonal", "annual": "Annual"}.get(kind)
    if unit:
        return " ".join(w for w in (unit, stat, subject) if w)
    if kind in CLIMATOLOGIES:
        unit = "monthly" if kind == "monthly_climatology" else "seasonal"
        if plain:
            return f"Long-term {unit} {subject}"
        if reducer == "sum":
            return f"Mean {unit} total {subject}"
        if reducer == "mean":
            return f"Mean {unit} {subject}"
        return f"Long-term {unit} {stat} {subject}"
    if reducer == "sum" and not plain:
        return f"Total {subject}"
    return title_label


def _span(panels: list[dict]) -> tuple[date, date]:
    starts = [date.fromisoformat(a) for p in panels for a, _b in p["ranges"]]
    ends = [date.fromisoformat(b) - timedelta(days=1) for p in panels for _a, b in p["ranges"]]
    return min(starts), max(ends)


def series_years(panels: list[dict]) -> int:
    """How many years the largest panel of a climatology averages over."""
    return max(len(p["ranges"]) for p in panels)


def series_subtitle(kind: str, panels: list[dict]) -> str:
    """The line under the title: the span of the series."""
    first, last = _span(panels)
    if kind in CLIMATOLOGIES:
        years = series_years(panels)
        return f"Average over {first.year} to {last.year} ({years} year{'s' if years != 1 else ''})"
    if kind == "custom":
        return f"{len(panels)} periods compared"
    if kind == "annual":
        return f"{first.year} to {last.year}"
    month = lambda d: _MONTHS[d.month - 1]
    if first.year == last.year:
        return f"{month(first)} to {month(last)} {first.year}"
    return f"{month(first)} {first.year} to {month(last)} {last.year}"


def series_processing(kind: str, reducer: str, n_images: int, plain: bool = False) -> str:
    """How the maps were made, for the credit block."""
    unit = _UNIT_WORD.get(kind, "period")
    what = "Most common class" if reducer == "mode" else f"{reducer.capitalize()} of the images"
    if kind in CLIMATOLOGIES and reducer == "sum" and not plain:
        text = f"Sum of the images of each {unit} in every year, averaged over the years"
    elif kind in CLIMATOLOGIES:
        text = f"{what} of each {unit} across all years"
    else:
        text = f"{what} in each {unit}"
    return f"{text} ({n_images} images in all)"
