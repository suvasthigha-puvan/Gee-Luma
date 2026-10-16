"""
connections.py
--------------
The checks behind the app's setup window: signing in to Google Earth
Engine, connecting to an Earth Engine project, and trying an AI key. Each
check answers with a message in plain words, or None when all is well.

Also tells which service's usage limit an error is about, so the app can
offer to switch to another Earth Engine project when that one's runs out.
"""

from __future__ import annotations

import re
import threading

import ee
from ee import oauth

from gee_luma.pipeline import create_llm

REGISTER_URL = "https://code.earthengine.google.com/register"
SIGN_IN_WAIT_S = 600


# ====================== Google sign-in ======================

def signed_in() -> bool:
    """Whether this computer holds a working Earth Engine sign-in."""
    try:
        return oauth.is_valid_credentials(ee.data.get_persistent_credentials())
    except Exception:
        return False


class SignIn:
    """
    Earth Engine's own browser sign-in ("localhost" mode): the person signs in
    with Google in a browser tab, Google sends the answer back to a small
    one-off web server here, and the sign-in is saved where `earthengine
    authenticate` saves it.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"         # idle | waiting | done | error
        self.url: str | None = None
        self.error: str | None = None

    def start(self) -> str:
        """The Google page to open; one sign-in at a time."""
        with self.lock:
            if self.state == "waiting" and self.url:
                return self.url
            flow = oauth.Flow("localhost:0")          # any free port
            flow.server.server.timeout = SIGN_IN_WAIT_S
            self.url, self.state, self.error = flow.auth_url, "waiting", None
            threading.Thread(target=self._wait, args=(flow,), daemon=True).start()
            return self.url

    def _wait(self, flow):
        try:
            flow.save_code()
            self.state = "done"
        except Exception as e:
            print(f"Earth Engine sign-in failed: {e}")
            self.error = "The Google sign-in was not finished. Try again."
            self.state = "error"


# ====================== Earth Engine project ======================

def connect_earth_engine(project: str) -> str | None:
    """Start Earth Engine with this project and run a tiny request on it."""
    try:
        ee.Initialize(project=project)
        ee.Number(1).getInfo()
        return None
    except Exception as e:
        print(f"Earth Engine project {project!r} could not be used: {e}")
        return earth_engine_problem(e, project)


def earth_engine_problem(error: Exception, project: str) -> str:
    text = str(error)
    low = text.lower()
    if "credentials" in low or "authorize" in low or "authenticate" in low or "refresh" in low:
        return "Sign in with Google first (step 1)."
    if "not registered" in low or "register" in low:
        return (f"The project \"{project}\" is not registered to use Earth Engine. "
                f"Register it (free for non-commercial use) at {REGISTER_URL}, then try again.")
    if "has not been used" in low or "is disabled" in low or "service_disabled" in low:
        return (f"The Earth Engine API is not turned on for \"{project}\". Turn it on at "
                f"https://console.cloud.google.com/apis/library/earthengine.googleapis.com?project={project} "
                "and try again in a minute.")
    if "not found" in low or "does not exist" in low or "invalid project" in low:
        return f"No Google Cloud project called \"{project}\" was found. Check the project ID (not its name)."
    if "permission" in low or "forbidden" in low or "403" in low or "serviceusage" in low:
        return (f"Your Google account cannot use the project \"{project}\". Check the project ID, "
                "or ask the project's owner to give your account Earth Engine access.")
    if limit_kind([text]) == "earthengine":
        return f"The project \"{project}\" has reached its Earth Engine usage limit. Try another project."
    return f"Earth Engine could not be started with \"{project}\" ({text[:200]})."


# ====================== AI service ======================

def check_llm(api_key: str, model: str) -> str | None:
    """Send the AI service a one-word request with this key and model."""
    try:
        create_llm(api_key, model).call("Reply with the single word OK.")
        return None
    except Exception as e:
        print(f"AI model {model!r} could not be used: {e}")
        text = str(e)
        low = text.lower()
        if isinstance(e, ImportError) or "not installed" in low or "pip install" in low:
            return f"The Python package for this AI service is missing ({text[:160]})."
        if "insufficient_quota" in low or "billing" in low or "credit" in low:
            return "This key has no credit left. Add credit with the AI service, or use another key."
        if "api key" in low or "api_key" in low or "401" in low or "authentication" in low or "unauthorized" in low:
            return "The AI service did not accept this key. Check that it was copied in full."
        if "model" in low and ("not found" in low or "does not exist" in low or "404" in low or "unsupported" in low):
            return f"The model \"{model}\" is not available with this key. Pick another model."
        if limit_kind([text]):
            return "This key has reached its usage limit. Wait a minute, or use another key."
        return f"The AI service could not be reached with this key and model ({text[:200]})."


# ====================== usage limits ======================

_LIMIT = re.compile(r"quota|rate.?limit|too many (concurrent|requests)|resource.?exhausted|capacity exceeded|\b429\b", re.I)
_AI_SERVICE = re.compile(r"openai|litellm|anthropic|gemini|gpt-|insufficient_quota|ratelimiterror|api.?key|tokens per", re.I)


def limit_kind(texts: list[str]) -> str | None:
    """"earthengine" or "llm" when one of these errors says a usage limit was reached."""
    for text in texts:
        if _LIMIT.search(text) and "memory" not in text.lower():
            return "llm" if _AI_SERVICE.search(text) else "earthengine"
    return None
