"""Memory: facts found during this run, company knowledge, and lessons from past mistakes."""
import json

import yaml

from agent import config


class Memory:
    """Working memory for ONE run. Remembers what each step found, and who found it."""

    def __init__(self):
        self.facts = {}      # latest value of every fact, e.g. {"invoice_number": "INV-1004"}
        self.history = []    # [{"step": 1, "source": "browser_read", "data": {...}}]

    def remember(self, step_id, data, source):
        clean = {k: v for k, v in (data or {}).items() if v not in (None, "")}
        self.facts.update(clean)
        self.history.append({"step": step_id, "source": source, "data": clean})


# ---- company knowledge (read from company_context.yaml) ----
def load_context():
    return yaml.safe_load(config.CONTEXT_FILE.read_text()) or {}


def context_text(ctx):
    return yaml.safe_dump(ctx, sort_keys=False, allow_unicode=True)


def policies_text(ctx):
    return "\n".join(f"- {p}" for p in ctx.get("policies", []))


# ---- lessons learned across runs (lessons.json) ----
def load_lessons():
    try:
        return json.loads(config.LESSONS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def add_lessons(new_lessons):
    """Save new lessons (no duplicates, keep the latest 20). Returns how many were really new."""
    lessons = load_lessons()
    added = 0
    for lesson in new_lessons:
        lesson = lesson.strip()[:240]
        if lesson and lesson not in lessons:
            lessons.append(lesson)
            added += 1
    config.LESSONS_FILE.write_text(json.dumps(lessons[-20:], indent=2))
    return added


def clear_lessons():
    if config.LESSONS_FILE.exists():
        config.LESSONS_FILE.unlink()
