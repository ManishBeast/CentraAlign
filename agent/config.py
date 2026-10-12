"""Settings, read from .env. One place to change the LLM provider or limits."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

APP_URL = os.getenv("APP_URL", "http://localhost:5050").rstrip("/")
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").split("#")[0].strip().lower()
HEADLESS = os.getenv("HEADLESS", "false").split("#")[0].strip().lower() == "true"
USE_VISION = os.getenv("LLM_VISION", "false").split("#")[0].strip().lower() == "true"
MAX_BROWSER_STEPS = int(os.getenv("MAX_BROWSER_STEPS", "20").split("#")[0])
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3").split("#")[0])
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()
]

RUNS_DIR = ROOT / "runs"
LESSONS_FILE = ROOT / "lessons.json"
CONTEXT_FILE = ROOT / "company_context.yaml"
ERP_FILE = ROOT / "erp_data.json"

DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-6",
    "groq": "openai/gpt-oss-120b",
}


KEY_ENV = {
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "groq": ("GROQ_API_KEY",),
}


def _has_key(provider):
    return any(os.getenv(k) for k in KEY_ENV.get(provider, ()))


def model_chain():
    """Ordered list of (provider, model) we are allowed to use."""
    raw = (os.getenv("LLM_CHAIN") or "").split("#")[0].strip()
    entries = []
    if raw:
        for item in raw.split(","):
            item = item.strip()
            if ":" in item:
                p, m = item.split(":", 1)
                entries.append((p.strip().lower(), m.strip()))
    else:
        primary = (os.getenv("LLM_MODEL") or "").split("#")[0].strip() or DEFAULT_MODELS.get(PROVIDER)
        entries.append((PROVIDER, primary))
        if PROVIDER == "gemini":
            entries += [("gemini", m) for m in GEMINI_FALLBACK_MODELS]
    usable = [(p, m) for p, m in entries if p in KEY_ENV and _has_key(p)]
    skipped = [f"{p}:{m}" for p, m in entries if (p, m) not in usable]
    if skipped:
        print(f"(config) skipping models with no API key / unknown provider: {skipped}")
    return usable


def make_llm_for(provider, model):
    if provider == "gemini":
        from browser_use import ChatGoogle
        return ChatGoogle(model=model)
    if provider == "openai":
        from browser_use import ChatOpenAI
        return ChatOpenAI(model=model)
    if provider == "anthropic":
        from browser_use import ChatAnthropic
        return ChatAnthropic(model=model)
    if provider == "groq":
        from browser_use import ChatGroq
        return ChatGroq(model=model)
    raise ValueError(f"Unknown provider '{provider}'. Use gemini, openai, anthropic or groq.")


def make_llm(model_override=None):
    """Kept for backward compatibility."""
    model = (
        model_override
        or (os.getenv("LLM_MODEL") or "").split("#")[0].strip()
        or DEFAULT_MODELS.get(PROVIDER)
    )
    return make_llm_for(PROVIDER, model)
