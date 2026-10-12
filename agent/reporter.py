"""Audit log (every decision, as JSON lines) and the final human-readable report."""
import json
import time
from datetime import datetime

from agent import config


class RunLog:
    def __init__(self):
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = config.RUNS_DIR / self.run_id
        self.evidence = self.dir / "evidence"
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.started = time.time()

    def say(self, text=""):
        print(text, flush=True)

    def event(self, kind, **data):
        record = {"t": round(time.time() - self.started, 1), "event": kind, **data}
        self.events.append(record)
        with open(self.dir / "audit.jsonl", "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def write_report(self, task, plan, status, verdict, facts, lessons_added, error=None):
        lines = [f"# Run {self.run_id}", "", f"**Task:** {task}", "",
                 f"**Status:** {status}", f"**Verification:** {verdict['verdict']}", ""]
        if error:
            lines += [f"**Error:** {error}", ""]
        if plan:
            lines += ["## Plan", ""] + [f"{s['id']}. `{s['tool']}`: {s['goal']}" for s in plan["steps"]] + [""]
        lines += ["## Independent checks", ""]
        for c in verdict["checks"]:
            mark = "PASS" if c["ok"] else "FAIL"
            lines.append(f"- [{mark}] {c['name']}" + (f" ({c['detail']})" if c["detail"] else ""))
        lines += ["", "## Facts the agent collected", "", "```json", json.dumps(facts, indent=2, default=str), "```", "",
                  "## Timeline", ""]
        for e in self.events:
            extra = {k: v for k, v in e.items() if k not in ("t", "event")}
            lines.append(f"- t={e['t']}s **{e['event']}** {json.dumps(extra, default=str)[:300]}")
        lines += ["", f"Lessons newly saved this run: {lessons_added}",
                  f"Evidence screenshots: `{self.evidence}`", f"Total time: {round(time.time() - self.started, 1)}s"]
        (self.dir / "report.md").write_text("\n".join(lines))
