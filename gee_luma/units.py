"""
units.py
--------
Units of the legend, worked out from the dataset's own units and from what
was done with the images.

A dataset states the units of one image: MODIS evapotranspiration is
"kg/m2/8day", CHIRPS rainfall "mm/d", TerraClimate rainfall "mm" (per month).
Once images are added up over a period those units no longer describe the
map: twelve monthly totals are in mm/month, annual totals in mm/year, and a
total over some other period simply in mm. Averages keep the dataset's own
rate, written out plainly (mm/day, mm/8 days).

Depths of water are given in mm: one kilogram of water on a square metre is
a layer one millimetre deep, and mm is how rainfall and evapotranspiration
are read.

Public API:
  whole_period(date_start, date_end)             -> "month" | "year" | None
  aggregated_units(units, reducer, period, water) -> units string
  relabel_units(label, reducer, period, hint)     -> label with corrected units
  is_water_depth(text)                            -> bool
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Words that mark a band as a depth of water (a flux of water per area).
_WATER_WORDS = ("evapotranspiration", "evaporation", "transpiration", "precipitation", "rainfall",
                "rain", "runoff", "snowfall", "snowmelt", "water equivalent", "irrigation",
                "water deficit", "recharge")
_WATER_KEYS = {"ET", "PET", "AET", "PRECIPITATION", "PR", "RO"}
_KG_PER_M2 = re.compile(r"^kg\s*(/\s*m\s*\^?2|\s*m\s*\^?-2)$", re.IGNORECASE)
# The period one image stands for, as datasets write it after the unit:
# "/d", "/day", "/8day", "/16 days", "/month", "/yr", "/year".
_PER_PERIOD = re.compile(
    r"^(?P<base>.*?)\s*(/|\bper\b)\s*(?P<n>\d+)?\s*-?\s*(?P<unit>d|day|days|pentad|dekad|decade|month|months|mo|yr|year|years|a)$",
    re.IGNORECASE)
# Rates per hour or second cannot be added up image by image; such units are left alone.
_FAST_RATE = re.compile(r"(/|\bper\b)\s*(s|sec|second|h|hr|hour)s?\b", re.IGNORECASE)
_PERIOD_NAMES = {"d": "day", "day": "day", "days": "day", "pentad": "pentad", "dekad": "dekad",
                 "decade": "dekad", "month": "month", "months": "month", "mo": "month",
                 "yr": "year", "year": "year", "years": "year", "a": "year"}


def is_water_depth(text: str) -> bool:
    """True when the words describing a band (name, title, theme) say it is a depth of water."""
    lower = str(text or "").lower().replace("_", " ")
    if any(re.search(r"\b" + re.escape(word) + r"\b", lower) for word in _WATER_WORDS):
        return True
    return any(key in _WATER_KEYS for key in re.findall(r"[A-Za-z]+", str(text or "").upper()))


def whole_period(date_start: str, date_end: str) -> str | None:
    """
    "month" or "year" when the dates span exactly one calendar month or year,
    else None. The end may be the last day of the period or the day after it.
    """
    try:
        start, end = date.fromisoformat(date_start), date.fromisoformat(date_end)
    except Exception:
        return None
    if start.day != 1:
        return None
    if end.day != 1:
        end += timedelta(days=1)        # last day of the period -> the day after it
    if end.day != 1:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months == 1:
        return "month"
    if months == 12 and start.month == 1:
        return "year"
    return None


def aggregated_units(units: str, reducer: str | None, period: str | None, water: bool) -> str:
    """
    Units of a map made from images whose units are `units`.

    reducer: how the images were combined ("sum", "mean", ...), or None when
             a single image is shown as it is.
    period:  for totals, what each map is the total of: "month", "season",
             "year", or None for a period that is none of these.
    water:   the band is a depth of water, so kg/m2 is written as mm.
    """
    units = str(units or "").strip()
    if not units:
        return units
    if _FAST_RATE.search(units):
        return units
    # Catalog spellings that say the same thing in more words:
    # "mm, daily total" is mm/day, "m of water equivalent" is m.
    units = re.sub(r"\s*,\s*daily\b.*$", "/day", units, flags=re.IGNORECASE)
    units = re.sub(r"\s+of water equivalent\b", "", units, flags=re.IGNORECASE)
    match = _PER_PERIOD.match(units)
    base = match.group("base").strip() if match else units
    if water and _KG_PER_M2.match(base):
        base = "mm"
    if reducer == "sum":
        return f"{base}/{period}" if period else base
    if not match:
        return base
    count, name = match.group("n"), _PERIOD_NAMES[match.group("unit").lower()]
    return f"{base}/{count} {name}s" if count and count != "1" else f"{base}/{name}"


def relabel_units(label: str, reducer: str | None, period: str | None, hint: str = "") -> str:
    """
    A legend label such as "Evapotranspiration (kg/m2/8day)" with its units
    made right for the map: "Evapotranspiration (mm/month)" for monthly totals.
    Labels without units in brackets come back unchanged.
    hint: further words about the band (its name, the map's theme).
    """
    match = re.match(r"^(?P<text>.*\S)\s*\((?P<units>[^()]*)\)\s*$", str(label))
    if not match:
        return label
    water = is_water_depth(f"{match.group('text')} {hint}")
    units = aggregated_units(match.group("units"), reducer, period, water)
    return f"{match.group('text')} ({units})" if units else match.group("text")
