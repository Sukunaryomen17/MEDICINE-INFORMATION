"""
List the Gemini models this API key can actually call.

Run this whenever extraction fails with a 404. A 404 on generateContent means
the model name does not exist for your key and API version -- it does NOT mean
the key is invalid, which is why the request still authenticates and still
fails.

    ./venv/bin/python list_models.py

Copy a working name into .env as GEMINI_MODEL, and one or two more as
GEMINI_MODEL_FALLBACKS (comma-separated) so a retired or rate-limited model
fails over instead of failing the request.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GOOGLE_API_KEY")
if not key:
    sys.exit("GOOGLE_API_KEY not set (checked .env and the environment)")

try:
    from google import genai
except ImportError:
    sys.exit("google-genai is not installed: pip install google-genai")

client = genai.Client(api_key=key)
print(f"key ...{key[-4:]}  |  SDK google-genai\n")

usable = []
try:
    for model in client.models.list():
        actions = list(getattr(model, "supported_actions", None) or [])
        if actions and "generateContent" not in actions:
            continue
        name = getattr(model, "name", "?")
        label = getattr(model, "display_name", "") or ""
        usable.append(name)
        print(f"  {name:<52} {label}")
except Exception as error:  # noqa: BLE001
    sys.exit(f"\nCould not list models: {error}")

if not usable:
    sys.exit("\nNo models supporting generateContent are available to this key.")

current = os.getenv("GEMINI_MODEL", "")
short = [n.removeprefix("models/") for n in usable]
print(f"\n{len(usable)} usable model(s). Current GEMINI_MODEL={current or '(unset)'}")
if current and current not in short and current not in usable:
    print(f"  WARNING: {current} is NOT in the list above - that is your 404.")
