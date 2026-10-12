"""
The main loop:  Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Report
Everything task-specific lives in the plan (made by the LLM) and company_context.yaml, not here.
"""
import time

from agent import approval, config, executor, memory as mem, planner, reporter, verifier


def is_fatal(error):
    """Errors that retrying cannot fix (bad API key etc.)."""
    text = str(error).lower()
    return any(k in text for k in ("401", "invalid_api_key", "api key not valid", "authentication", "permission denied"))


class Run:
    def __init__(self, task, auto_approve=False):
        self.task = task
        self.auto = auto_approve
        self.log = reporter.RunLog()
        self.memory = mem.Memory()
        self.context = mem.load_context()
        self.lessons = mem.load_lessons()
        self.browser = None
        self.write_planned = False
        self.status = "COMPLETED"
        self.lessons_added = 0

    # ------------------------------------------------------------------ main
    async def run(self):
        log = self.log
        log.say(f"\nTask: {self.task}")
        log.say(f"Run id: {log.run_id}  (lessons loaded: {len(self.lessons)})\n")
        log.event("start", task=self.task, lessons_loaded=len(self.lessons))

        try:
            before = verifier.fetch_bills()
        except Exception as e:  # noqa: BLE001
            log.say(f"Cannot reach the sandbox at {config.APP_URL}. Start it first: python app.py --reset\n({e})")
            return {"status": "ERROR", "verdict": "NONE", "facts": {}}

        plan, error = None, None
        try:
            plan = await self.make_plan()
            if not plan["steps"]:
                raise ValueError("The planner produced no steps.")
            self.write_planned = any(s["tool"] == "browser_write" for s in plan["steps"])

            self.browser = executor.make_browser()
            for step in plan["steps"]:
                log.say(f"[Step {step['id']}/{len(plan['steps'])}] {step['tool']}: {step['goal']}")
                if not await self.do_step(step):
                    self.status = "STOPPED"
                    log.say(f"   Stopped at step {step['id']}.")
                    break
        except Exception as e:  # noqa: BLE001
            self.status, error = "ERROR", f"{type(e).__name__}: {str(e)[:300]}"
            log.say(f"\nERROR: {error}")
            log.event("error", error=error)
        finally:
            if self.browser is not None:
                await executor.close_browser(self.browser)

        # ---- Verify: independent of the agent ----
        try:
            after = verifier.fetch_bills()
            verdict = verifier.verify(before, after, self.memory.facts, self.write_planned)
        except Exception as e:  # noqa: BLE001
            verdict = {"verdict": "UNVERIFIABLE", "checks": [{"name": "Reach ERP for verification", "ok": False, "detail": str(e)}]}
        if self.status != "COMPLETED":
            verdict["verdict"] = "NOT COMPLETED"
        log.event("verification", verdict=verdict["verdict"], checks=verdict["checks"])

        self.print_summary(verdict)
        log.write_report(self.task, plan, self.status, verdict, self.memory.facts, self.lessons_added, error)
        return {"status": self.status, "verdict": verdict["verdict"], "facts": self.memory.facts, "run_id": log.run_id}

    # ------------------------------------------------------------------ understand + plan
    async def make_plan(self):
        plan = await planner.make_plan(self.task, self.context, self.lessons)
        if plan["clarification_needed"]:
            self.log.event("clarification_asked", question=plan["clarification_needed"])
            answer = approval.ask_human(plan["clarification_needed"])
            self.task = f"{self.task}\n(Clarification from the user: {answer})"
            self.log.event("clarification_answered", answer=answer)
            plan = await planner.make_plan(self.task, self.context, self.lessons)
        self.log.event("plan", goal=plan["goal"], steps=plan["steps"])
        self.log.say(f"Goal understood: {plan['goal']}\n")
        return plan

    # ------------------------------------------------------------------ one step
    async def do_step(self, step):
        if step["tool"] == "ask_human":
            answer = approval.ask_human(step["question"])
            self.memory.remember(step["id"], {"human_answer": answer}, "human")
            self.log.event("human_input", step=step["id"], answer=answer)
            return True

        if step["tool"] == "browser_write":
            # Idempotency: never create a duplicate record.
            inv = self.memory.facts.get("invoice_number")
            if isinstance(inv, str) and inv.strip():
                existing = [b for b in verifier.fetch_bills() if b["invoice_number"] == inv.strip()]
                if existing:
                    self.log.say(f"   {inv} is already in the ERP (id {existing[0]['id']}). Skipping the write to avoid a duplicate.")
                    self.log.event("skip_write", step=step["id"], reason="record already exists", invoice=inv)
                    return True
            approved = approval.approve_write(step, self.memory.facts, self.auto)
            self.log.event("approval", step=step["id"], approved=approved, facts=self.memory.facts)
            if not approved:
                self.log.say("   Write was not approved. Nothing was changed.")
                return False

        return await self.attempt_loop(step)

    async def attempt_loop(self, step):
        """Execute -> Observe -> Adapt. Retry with feedback, then ask a human."""
        tool, feedback = step["tool"], None
        max_attempts, attempt, hint_used = config.MAX_ATTEMPTS, 0, False

        while True:
            attempt += 1
            self.log.say(f"   attempt {attempt}/{max_attempts} ...")
            bills_before = verifier.fetch_bills() if tool == "browser_write" else None
            try:
                result = await executor.run_step(self.task, step, self.memory.facts, self.context, self.lessons,
                                                 self.browser, feedback, self.log.evidence, attempt)
            except Exception as e:  # noqa: BLE001
                if is_fatal(e):
                    raise
                result = {"success": False, "data": {}, "problems_seen": [], "screenshots": [],
                          "summary": f"Operator crashed: {str(e)[:200]}"}

            ok, why = self.judge(step, result, bills_before)
            self.log.event("observation", step=step["id"], attempt=attempt, accepted=ok, reported_success=result["success"],
                           summary=result["summary"], problems_seen=result["problems_seen"],
                           data=result["data"], screenshots=result["screenshots"], judgement=why)
            self.log.say(f"   observed: {result['summary'] or '(no summary)'}")

            if ok:
                self.memory.remember(step["id"], result["data"], tool)
                if tool == "browser_write" and result["problems_seen"]:
                    new = mem.add_lessons([f"The ERP form rejected an entry with this message: {p}" for p in result["problems_seen"]])
                    self.lessons_added += new
                    self.log.say(f"   learned {new} new lesson(s) from the errors it hit.")
                    self.log.event("lesson_saved", lessons=result["problems_seen"])
                return True

            feedback = why
            if result["problems_seen"]:
                feedback += "\nErrors the site showed: " + " | ".join(result["problems_seen"])
            self.log.say(f"   not accepted: {why}")
            self.log.event("retry", step=step["id"], attempt=attempt, reason=why)

            if attempt >= max_attempts:
                if hint_used:
                    return False
                hint = approval.ask_human(
                    f"Step {step['id']} failed {attempt} times.\nGoal: {step['goal']}\nLast problem: {why}\n"
                    "Type a hint and I will try once more, or press Enter to stop.")
                if not hint:
                    return False
                hint_used, max_attempts = True, max_attempts + 1
                feedback += f"\nHuman hint: {hint}"
                self.log.event("human_hint", step=step["id"], hint=hint)

    def judge(self, step, result, bills_before):
        """Decide if a step really worked, using ground truth where possible (not just what the operator claims)."""
        if step["tool"] == "browser_write":
            saved = len(verifier.fetch_bills()) > len(bills_before)
            if saved:
                return True, "A new bill exists in the ERP."
            return False, "The ERP shows no new bill, so the entry was NOT saved. " + (result["summary"] or "")
        if not result["success"]:
            return False, "The operator reported failure. " + (result["summary"] or "")
        missing = [k for k in step["outputs"] if result["data"].get(k) in (None, "")]
        if missing:
            return False, f"The answer is missing required values: {missing}. Reply in the required JSON shape with every value."
        return True, "All required values found."

    # ------------------------------------------------------------------ final output
    def print_summary(self, verdict):
        log = self.log
        log.say("\n" + "=" * 62)
        log.say(f"  STATUS: {self.status}      VERIFICATION: {verdict['verdict']}")
        log.say("=" * 62)
        for c in verdict["checks"]:
            log.say(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}" + (f"  ({c['detail']})" if c["detail"] else ""))
        if self.memory.facts:
            log.say("\n  What the agent found/did:")
            for k, v in self.memory.facts.items():
                log.say(f"    {k}: {v}")
        log.say(f"\n  Report + evidence: runs/{log.run_id}/")
        log.say("=" * 62 + "\n")


async def run_task(task, auto_approve=False):
    return await Run(task, auto_approve).run()
