"""Talking to the LLM: automatic model fallback, and pulling JSON out of replies."""
import json
import re

from agent.llm_pool import pool, is_recoverable


def get_llm():
    """Kept for compatibility: the first model that is currently available."""
    return pool.pick()[1]


def extract_json(text):
    """Find the first JSON object in a model reply (ignores code fences and extra words)."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def ask(system, user):
    """One plain-text LLM call. On rate limit / quota, switches to the next model."""
    try:
        from browser_use.llm.messages import SystemMessage, UserMessage
    except ImportError:  # older/newer layouts
        from browser_use.llm import SystemMessage, UserMessage

    last = None
    for _ in range(len(pool.chain) * 2 + 1):
        label, llm = await pool.acquire()
        try:
            resp = await llm.ainvoke([SystemMessage(content=system), UserMessage(content=user)])
            out = resp.completion
            return out if isinstance(out, str) else str(out)
        except Exception as e:  # noqa: BLE001
            if not is_recoverable(e):
                raise
            pool.mark_failed(label, e)
            last = e
    raise last


async def ask_json(system, user):
    """Ask for JSON; if the reply is not valid JSON, ask once more."""
    text = await ask(system, user)
    data = extract_json(text)
    if data is None:
        text = await ask(system, user + "\n\nYour last reply was not valid JSON. Reply with ONLY one JSON object.")
        data = extract_json(text)
    if data is None:
        raise ValueError("The model did not return valid JSON: " + text[:200])
    return data