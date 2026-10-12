"""
Executor: does ONE plan step in a real browser by handing a narrow sub-goal to browser-use.
browser-use is the "hands" (clicking, typing, reading pages). Everything about WHAT to do,
retries, approvals and verification is our own code around it.
"""
import json
import shutil

from agent import config
from agent.llm import extract_json
from agent.llm_pool import pool, is_recoverable
from agent.memory import policies_text


def make_browser():
    from browser_use import Browser
    # keep_alive=True: one browser window is reused across all steps of a run
    return Browser(headless=config.HEADLESS, keep_alive=True)


async def close_browser(browser):
    for name in ("kill", "stop"):
        fn = getattr(browser, name, None)
        if fn:
            try:
                await fn()
                return
            except Exception:  # noqa: BLE001
                continue


def build_task(task, step, facts, context, lessons, feedback):
    sites = ", ".join(s["url"] for s in context.get("systems", {}).values())
    outputs = ", ".join(step["outputs"]) or "whatever the step asks for"
    lesson_block = "\n".join(f"- {l}" for l in lessons) or "(none)"
    feedback_block = f"\nPREVIOUS ATTEMPT FAILED. Fix this time:\n{feedback}\n" if feedback else ""
    return f"""You are a careful operator working in a company sandbox using a web browser.
Only use these sites: {sites}. Do not visit anything else.

OVERALL REQUEST: {task}
YOUR CURRENT STEP ({step['tool']}): {step['goal']}
This step is done when: {step['done_when'] or 'the step goal is achieved'}

FACTS ALREADY KNOWN FROM EARLIER STEPS:
{json.dumps(facts, indent=2) if facts else '(none)'}

COMPANY POLICIES (follow them):
{policies_text(context)}

LESSONS FROM PAST RUNS (follow them):
{lesson_block}
{feedback_block}
RULES:
- Do only this step, nothing more.
- When READING, copy values exactly as shown on the page.
- When WRITING into a form, convert values to the format the form needs. If the form shows an
  error message, read it, fix the field, and submit again. Copy every error message you saw.
- Never guess. If you cannot find something, say so and set success to false.

FINAL ANSWER: reply with ONLY one JSON object, no markdown, in this shape:
{{"success": true, "data": {{...}}, "problems_seen": ["exact error messages shown by the sites"], "summary": "one sentence"}}
For "data" include these keys: {outputs}. For a write step, "data" holds the values you actually entered."""


def parse_result(raw):
    data = extract_json(raw or "")
    if not isinstance(data, dict):
        return {"success": False, "data": {}, "problems_seen": [], "format_error": True,
                "summary": (raw or "")[:300] or "The operator returned no answer."}
    return {
        "success": bool(data.get("success")),
        "data": data["data"] if isinstance(data.get("data"), dict) else {},
        "problems_seen": [str(p) for p in (data.get("problems_seen") or [])],
        "summary": str(data.get("summary") or ""),
    }


def _make_agent(task_text, browser, llm):
    from browser_use import Agent

    kwargs = dict(task=task_text, llm=llm, browser=browser, use_vision=config.USE_VISION)
    try:
        return Agent(use_judge=False, **kwargs)   # skip the extra self-judging call (saves tokens)
    except TypeError:
        return Agent(**kwargs)


async def run_step(task, step, facts, context, lessons, browser,
                   feedback, evidence_dir, attempt):
    """Run one step. On rate-limit/quota errors, switch to the next model in the chain."""
    task_text = build_task(task, step, facts, context, lessons, feedback)

    last_error, history = None, None

    for _ in range(len(pool.chain) * 2 + 1):
        label, llm = await pool.acquire()
        print(f"   Using model: {label}")
        try:
            agent = _make_agent(task_text, browser, llm)
            history = await agent.run(max_steps=config.MAX_BROWSER_STEPS)

            # browser-use sometimes swallows LLM errors and just returns no result
            try:
                errs = " ".join(str(e) for e in (history.errors() or []) if e)
            except Exception:  # noqa: BLE001
                errs = ""
            if history.final_result() is None and errs and is_recoverable(errs):
                raise RuntimeError(errs[:300])

            last_error = None
            break

        except Exception as e:  # noqa: BLE001
            if not is_recoverable(e):
                raise
            last_error = e
            pool.mark_failed(label, e)

            # Never retry a write blindly: the failed model may already have saved the bill.
            if step["tool"] == "browser_write":
                from agent import verifier
                invoice = facts.get("invoice_number")
                if invoice:
                    matches = [b for b in verifier.fetch_bills() if b.get("invoice_number") == invoice]
                    if matches:
                        return {
                            "success": True, "data": dict(facts), "problems_seen": [],
                            "summary": "Invoice already appears in the ERP after a model error; "
                                       "relying on final verification instead of retrying.",
                            "screenshots": [],
                        }

    if last_error is not None:
        raise last_error

    result = parse_result(history.final_result())

    saved = []
    try:  # keep the last screenshot as evidence (best effort)
        shots = [p for p in (history.screenshot_paths() or []) if p]
        if shots:
            dest = evidence_dir / f"step{step['id']}_attempt{attempt}.png"
            shutil.copy(shots[-1], dest)
            saved.append(str(dest.name))
    except Exception:  # noqa: BLE001
        pass

    result["screenshots"] = saved
    return result