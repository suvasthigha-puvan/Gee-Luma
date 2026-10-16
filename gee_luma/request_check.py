"""
request_check.py
----------------
A first look at the request, before any dataset is searched: does it say
what to map and where?

Text that is not a map request at all ("asdf", "hello") would otherwise go
on to the dataset search, which always finds something - and the person
would be asked to choose between datasets for a map they never described.

The check is lenient: a request with a subject (a variable, index, dataset
or kind of image) and a place goes ahead, whatever its wording or language.
A missing period is fine - the pipeline picks a sensible default.

Public API:
  check_request(prompt, llm, has_uploaded_region) -> str | None
"""

from __future__ import annotations

import json
import re


def _json(answer) -> dict:
    text = str(answer or "")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def check_request(prompt: str, llm, has_uploaded_region: bool = False) -> str | None:
    """
    None when the request can be mapped; otherwise a message telling the
    person what is missing.

    Never blocks a request because of its own failure: if the language model
    cannot be reached or answers oddly, the request goes ahead.
    """
    if not re.search(r"[^\W\d_]{2}", prompt):
        return _message(subject=False, place=has_uploaded_region)
    try:
        answer = llm.call(
            f'A user of an application that makes maps from satellite data typed: "{prompt}"\n\n'
            "Answer two questions about this text, in whatever language it is written:\n"
            "1. subject: does it name something that can be mapped - a variable, index, dataset, sensor, "
            "satellite or kind of image (NDVI, rainfall, land cover, elevation, temperature, Sentinel-2, "
            "true colour, night lights, ...)? Be generous: any recognisable map subject counts, even "
            "misspelt or abbreviated.\n"
            "2. place: does it name a place on Earth (country, region, district, city, continent, river "
            "basin, coordinates, ...)?\n"
            "Random letters, greetings, questions unrelated to maps and other text that describes no map "
            "have neither.\n"
            'Return ONLY valid JSON: {"subject": true, "place": true}'
        )
        parsed = _json(answer)
    except Exception:
        return None
    subject = parsed.get("subject") is not False
    place = parsed.get("place") is not False or has_uploaded_region
    if subject and place:
        return None
    return _message(subject=subject, place=place)


def _message(subject: bool, place: bool) -> str:
    if not subject and not place:
        lead = "This doesn't look like a map request"
    elif not subject:
        lead = "The request doesn't say what to map"
    else:
        lead = "The request doesn't say where to map (name a place, or upload a GeoJSON boundary)"
    return (f"{lead}, so no map was generated. Describe what to map and where - for example "
            '"NDVI of Sri Lanka in 2023" or "Land cover map of Kandy district".')
