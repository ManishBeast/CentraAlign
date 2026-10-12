"""Planner: turns a plain-English request into a short list of steps, using company knowledge."""
from agent.llm import ask_json
from agent.memory import context_text

ALLOWED_TOOLS = {"browser_read", "browser_write", "ask_human"}

SYSTEM = (
    "You are the planning module of an autonomous operations agent that works inside a company's "
    "websites. You do NOT perform actions. You only create a plan. Reply with ONE JSON object and nothing else."
)

TOOLS_DOC = """TOOLS you can plan with:
- browser_read : a browser operator looks things up on a website and reports facts. Changes nothing.
- browser_write: a browser operator enters or changes data in a system. Needs human approval.
- ask_human    : ask the user something you cannot find yourself."""

SCHEMA = """Reply in exactly this JSON shape:
{
  "goal": "one sentence: the real outcome the user wants",
  "clarification_needed": null,
  "steps": [
    {"tool": "browser_read", "goal": "clear instruction for an operator who sees only this step",
     "outputs": ["vendor", "invoice_number", "amount", "due_date"],
     "done_when": "how we know this step worked"}
  ]
}"""

RULES = """PLANNING RULES:
- Use 1 to 4 steps. Do not invent extra steps.
- If the request is missing something essential that changes the outcome (for example WHICH vendor),
  set "clarification_needed" to one short question and set "steps" to [].
- If the user only wants information, use ONLY browser_read steps (no browser_write).
- If the user wants something recorded in a system, first read the facts (browser_read), then write them (browser_write).
- In every step "goal", name the exact site/system to use and apply the company policies below.
- Fact names are snake_case. Always call the invoice id "invoice_number", the money "amount", the due date "due_date", the vendor "vendor".
- A read step reports values EXACTLY as shown on the page. The write step converts them to the format the form needs."""


async def make_plan(task, context, lessons):
    lesson_block = "\n".join(f"- {l}" for l in lessons) or "(none yet)"
    user = (
        f"{TOOLS_DOC}\n\n{RULES}\n\n{SCHEMA}\n\n"
        f"COMPANY KNOWLEDGE:\n{context_text(context)}\n"
        f"LESSONS FROM PAST RUNS:\n{lesson_block}\n\n"
        f"USER REQUEST: {task}"
    )
    return validate_plan(await ask_json(SYSTEM, user))


def validate_plan(plan):
    """Check the model's plan is usable. Fails loudly instead of running something odd."""
    if not isinstance(plan, dict):
        raise ValueError("Planner did not return a JSON object")
    steps = []
    for i, raw in enumerate(plan.get("steps") or [], 1):
        tool = raw.get("tool")
        if tool not in ALLOWED_TOOLS:
            raise ValueError(f"Planner chose an unknown tool: {tool!r}")
        goal = str(raw.get("goal") or "").strip()
        if not goal:
            raise ValueError(f"Step {i} has no goal")
        steps.append({
            "id": i,
            "tool": tool,
            "goal": goal,
            "outputs": [str(o) for o in (raw.get("outputs") or [])],
            "done_when": str(raw.get("done_when") or ""),
            "question": str(raw.get("question") or goal),
        })
    return {
        "goal": str(plan.get("goal") or ""),
        "clarification_needed": plan.get("clarification_needed") or None,
        "steps": steps,
    }
