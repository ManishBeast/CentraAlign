"""Model pool: tries models in order, puts a failing one on cooldown, moves to the next."""
import asyncio
import time

from agent import config

COOLDOWN_RATE = 65            # per-minute rate limit: try again after ~1 minute
COOLDOWN_QUOTA = 6 * 3600     # daily / quota exhausted
COOLDOWN_DEAD = 24 * 3600     # bad key, wrong model name
MAX_WAIT = 75                 # if every model is cooling, wait at most this long

RATE_WORDS = ("429", "413", "rate limit", "rate_limit", "overloaded", "timeout", "timed out",
              "503", "502", "temporarily unavailable", "truncated", "max_output_tokens")
QUOTA_WORDS = ("quota", "resource_exhausted", "per day", "daily", "insufficient_quota",
               "billing", "exceeded your current")
DEAD_WORDS = ("401", "403", "404", "invalid_api_key", "api key not valid", "authentication",
              "permission denied", "not found", "model_not_found", "does not exist")


class AllModelsBusy(Exception):
    pass


def _text(error):
    return str(error).lower()


def is_recoverable(error):
    t = _text(error)
    return any(k in t for k in RATE_WORDS + QUOTA_WORDS + DEAD_WORDS)


class ModelPool:
    def __init__(self):
        self.chain = config.model_chain()
        self.cool_until = {}
        self._llms = {}

    @staticmethod
    def label(entry):
        return f"{entry[0]}:{entry[1]}"

    def _ready(self):
        now = time.time()
        return [e for e in self.chain if self.cool_until.get(self.label(e), 0) <= now]

    def _build(self, entry):
        lab = self.label(entry)
        if lab not in self._llms:
            self._llms[lab] = config.make_llm_for(*entry)
        return lab, self._llms[lab]

    def pick(self):
        if not self.chain:
            raise RuntimeError("No usable models. Check LLM_CHAIN and your API keys in .env")
        ready = self._ready()
        if not ready:
            raise AllModelsBusy("All models are cooling down.")
        return self._build(ready[0])

    async def acquire(self):
        """Return (label, llm) for the first available model; wait briefly if all are cooling."""
        while True:
            try:
                return self.pick()
            except AllModelsBusy:
                wait = min(self.cool_until.values()) - time.time()
                if wait > MAX_WAIT:
                    raise
                print(f"   (all models busy, waiting {int(wait) + 1}s...)")
                await asyncio.sleep(max(wait, 1))

    def mark_failed(self, label, error):
        t = _text(error)
        if any(k in t for k in QUOTA_WORDS):
            secs = COOLDOWN_QUOTA
        elif any(k in t for k in DEAD_WORDS) and not any(k in t for k in ("429", "rate limit")):
            secs = COOLDOWN_DEAD
        else:
            secs = COOLDOWN_RATE
        self.cool_until[label] = time.time() + secs
        print(f"   {label} unavailable for {secs // 60} min -> switching model")

    def status(self):
        now = time.time()
        return [{"model": self.label(e),
                 "cooldown_s": max(0, int(self.cool_until.get(self.label(e), 0) - now))}
                for e in self.chain]


pool = ModelPool()