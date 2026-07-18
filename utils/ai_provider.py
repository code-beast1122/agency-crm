"""Chat completions for the CRM assistant: NVIDIA NIM first, Groq as backup.

NIM speaks the OpenAI protocol, so the openai SDK talks to it by pointing
base_url at NVIDIA's endpoint -- there is no NVIDIA-specific client to learn.

Why two providers: NIM is the better model, but a rate limit, an expired key or
an outage there would otherwise leave the admin staring at an error. Groq is
already wired up and paid for, so it costs little to keep it as a floor. The
order is deliberate -- quality first, availability second.

Returns dicts ({"status": "success"|"error", ...}) rather than raising, matching
the convention in api_integrations.py and ai_summary.py so callers stay uniform.
"""
import os

from openai import OpenAI

# NVIDIA's hosted NIM endpoint. Self-hosted NIM containers expose the same API
# on a different host, so this is overridable rather than hardcoded.
NIM_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Overridable without a code change: the NIM catalog moves, and a model that is
# available today can be retired. Verified against the live /models list.
NIM_MODEL = os.environ.get("NVIDIA_MODEL", "minimaxai/minimax-m3")

# The fallback. Deliberately NOT llama-3.1-8b-instant, which is what made the
# assistant unusable in the first place -- a fallback that hallucinates is not a
# fallback, it is a quieter failure.
GROQ_MODEL = os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")

# An unbounded call freezes the portal: Streamlit reruns the script top to
# bottom and the user cannot interact while this is in flight.
CHAT_TIMEOUT = 90.0


def _nim_chat(messages, temperature, max_tokens):
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")

    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key, timeout=CHAT_TIMEOUT)
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _groq_chat(messages, temperature, max_tokens):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    from groq import Groq

    client = Groq(api_key=api_key, timeout=CHAT_TIMEOUT)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


# Tried in order. First one that answers wins.
PROVIDERS = (
    ("NVIDIA NIM", NIM_MODEL, _nim_chat),
    ("Groq", GROQ_MODEL, _groq_chat),
)


def chat(messages, temperature=0.3, max_tokens=1024):
    """Ask the best available model, falling back on failure.

    Returns {"status": "success", "content", "provider", "model", "fell_back"}
    or {"status": "error", "message"} when every provider failed -- with each
    provider's own error included, since "the assistant is broken" is useless to
    debug when two services could be at fault.
    """
    errors = []
    for index, (name, model, call) in enumerate(PROVIDERS):
        try:
            content = call(messages, temperature, max_tokens)
        except Exception as e:
            errors.append("{}: {}".format(name, e))
            continue

        if not content:
            # A provider that returns nothing has not answered. Treat it as a
            # failure so the next one gets its turn, rather than rendering blank.
            errors.append("{}: returned an empty response".format(name))
            continue

        return {
            "status": "success",
            "content": content,
            "provider": name,
            "model": model,
            # True when something ahead of this provider failed, so the caller
            # can say so instead of silently serving the weaker answer.
            "fell_back": index > 0,
            "errors": errors,
        }

    return {"status": "error", "message": "; ".join(errors) or "no provider configured"}
