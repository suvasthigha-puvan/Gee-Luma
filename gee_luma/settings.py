"""
settings.py
-----------
Gee-Luma's settings, kept in a .env file and nowhere else.

The setup window in the app writes them here, so a person never has to
edit the file by hand:

    EE_PROJECT    Earth Engine project ID
    LLM_MODEL     AI model, as provider/model (e.g. openai/gpt-4o-mini)
    LLM_API_KEY   key for that AI service
    PORT          port for server.py

The nearest .env file is used: in the Gee-Luma folder or any folder above
it. When there is none, one is created in the Gee-Luma folder. Only the
file is read; environment variables of the same name are ignored. Settings from older
versions (OPENAI_API_KEY, GEE_LUMA_MODEL) are still read, and replaced by
the new names on the next save.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

APP_DIR = Path(__file__).resolve().parent.parent


def _find_env() -> Path:
    for folder in (APP_DIR, *APP_DIR.parents):
        if (folder / ".env").is_file():
            return folder / ".env"
    return APP_DIR / ".env"


ENV_PATH = _find_env()
DEFAULT_PORT = 8000

# Current name -> the name older versions used.
_OLD_NAMES = {"LLM_API_KEY": "OPENAI_API_KEY", "LLM_MODEL": "GEE_LUMA_MODEL"}

_values: dict[str, str] = {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()} if ENV_PATH.exists() else {}


def get(name: str) -> str:
    """A setting's value ("" when it is not set)."""
    value = _values.get(name, "").strip()
    if not value and name in _OLD_NAMES:
        value = _values.get(_OLD_NAMES[name], "").strip()
    return value


def save(values: dict[str, str]) -> None:
    """Write settings to the .env file (creating it if needed) and use them at once."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Gee-Luma settings, written by the app's setup window.\n", encoding="utf-8")
    for name, value in values.items():
        set_key(str(ENV_PATH), name, value, quote_mode="always")
        _values[name] = value
        old = _OLD_NAMES.get(name)
        if old and old in _values:
            unset_key(str(ENV_PATH), old, quote_mode="always")
            _values.pop(old)


def port() -> int:
    """The server's port; on the first start it is written to the .env file."""
    value = get("PORT")
    if value.isdigit():
        return int(value)
    if value:
        raise SystemExit(f"PORT in {ENV_PATH} is not a number: {value!r}")
    save({"PORT": str(DEFAULT_PORT)})
    return DEFAULT_PORT


def key_hint(key: str) -> str:
    """Enough of a key to recognise it, never the key itself."""
    return f"…{key[-4:]}" if len(key) > 8 else "saved"
