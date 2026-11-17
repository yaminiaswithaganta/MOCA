"""
One place that talks to an AI model, used by "Ask the manual" and the PDF report's summary.

Uses Claude when ANTHROPIC_API_KEY is set, otherwise OpenAI when OPENAI_API_KEY is set.
"""

import os

import anthropic
import openai

CLAUDE_MODEL = os.environ.get("MOCA_MANUAL_MODEL", "claude-opus-5-5")
OPENAI_MODEL = os.environ.get("MOCA_OPENAI_MODEL", "gpt-5-mini")

# what callers catch, whichever service answered
AuthError = (anthropic.AuthenticationError, openai.AuthenticationError)
RateLimited = (anthropic.RateLimitError, openai.RateLimitError)
Failed = (anthropic.APIStatusError, anthropic.APIConnectionError,
          openai.APIStatusError, openai.APIConnectionError)

_clients = {}


def provider():
    """Which AI answers: "claude" if its key is set, else "openai", else None."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def complete(system, prompt):
    """The model's text reply to one prompt."""
    if provider() == "openai":
        client = _clients.setdefault("openai", openai.OpenAI())
        response = client.responses.create(model=OPENAI_MODEL, instructions=system, input=prompt)
        return response.output_text.strip()
    client = _clients.setdefault("claude", anthropic.Anthropic())
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                     # if a safety check declines, another model answers
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()
