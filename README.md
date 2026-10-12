# OpsPilot: an autonomous task worker (CentrAlign AI, AI Engineering Intern assignment)

OpsPilot takes a plain-English company request, such as *"Find the latest invoice from Company X, extract the amount and due date, enter it into our internal system, and tell me once it is done"*, and completes it by operating a real browser. It does not trust its own "done": a separate checker re-reads the source and the saved data with plain code and returns a verdict plus evidence.

```
Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Report
```

## What is in the box

| Part | What it is |
|---|---|
| `app.py` | A **sandbox company** (Flask): a vendor portal (where invoices live) and an internal ERP (where bills must be entered). No real systems or credentials are used anywhere. |
| `agent/` | The agent: planner, executor, memory, approvals, verifier, reporter and the loop that connects them. |
| `company_context.yaml` | What the agent knows about how this company works (systems, procedures, policies). |
| `tasks.yaml` | Demo tasks written as a user would type them. |

The sandbox has deliberate traps, so the agent has to be smart rather than lucky:

1. **A draft invoice looks newest** (INV-1007). The real latest invoice is INV-1004. The company policy file tells the agent that drafts are not real invoices.
2. **Format mismatch.** The vendor page shows `$2,450.75` and `Sep 14, 2026`. The ERP only accepts `2450.75` and `14-09-2026` and rejects anything else with an error message. The agent has to read the error, fix the form and resubmit.
3. **Duplicates.** The ERP rejects an invoice number that already exists, and the agent checks first so it never creates one.

## Setup

Python 3.11+ (developed on 3.12, macOS).

```bash
conda create -n myproject312 python=3.12 -y     # or any 3.11+ environment
conda activate myproject312
pip install -r requirements.txt
cp .env.example .env                            # then put ONE provider key in .env
```

Edit `.env`: pick `LLM_PROVIDER` (`gemini`, `openai`, `anthropic` or `groq`) and add that provider's API key. Never commit `.env`.

Google Chrome must be installed (browser-use drives it).

## Run

Terminal 1: start the sandbox company and leave it running:

```bash
python app.py --reset
```

Terminal 2: give the agent work:

```bash
python run.py --list                 # show the demo tasks
python run.py --task 1               # run demo task 1
python run.py "Find the latest invoice from Company X and enter it into our internal system"
```

Useful commands:

```bash
python run.py --task 1 --auto-approve   # skip the "Approve? [y/N]" question (testing only)
python run.py --reset-erp               # empty the ERP bills
python run.py --clear-lessons           # make the agent forget what it learned
python -m pytest -q                     # unit tests for the checker logic
```

Open `http://localhost:5050/erp` in a normal browser at any time to see what the ERP contains.

Each run writes `runs/<run-id>/` containing `report.md` (summary, plan, independent checks, timeline), `audit.jsonl` (every decision, as JSON) and `evidence/` (screenshots).

## Architecture

```
 user request
      |
      v
 [Planner] --(company_context.yaml + lessons.json)--> plan: 1-4 steps, each with a tool
      |            \__ if the request is ambiguous -> ask the human, then re-plan
      v
 for each step:
   [Policy gate]   write steps: skip if the record already exists, else ask the human to approve
      |
   [Executor]      hands ONE narrow sub-goal to browser-use (real Chrome), with facts + policies + lessons
      |
   [Observe/Judge] ground-truth check in code (did a new ERP record really appear?). If not: retry
      |            with the failure fed back; after N attempts ask the human for a hint
   [Memory]        facts found are remembered for later steps; ERP errors become lessons for future runs
      |
      v
 [Verifier]  re-reads the vendor page with plain HTTP and the ERP via its JSON API,
             compares them field by field, and checks for side effects and duplicates
      |
      v
 [Reporter]  verdict + evidence + audit trail
```

| File | Responsibility |
|---|---|
| `agent/planner.py` | Turns the request into a validated plan. Rejects plans with unknown tools or empty goals. |
| `agent/executor.py` | Runs one step through browser-use and parses its JSON answer. |
| `agent/runner.py` | The loop: approval, retry, escalation, idempotency, memory, verification. |
| `agent/verifier.py` | Independent verification (no LLM involved). |
| `agent/memory.py` | Working memory for a run, company knowledge, and persistent lessons. |
| `agent/approval.py` | Asks the human for approval or input. |
| `agent/reporter.py` | Audit log and `report.md`. |
| `agent/llm.py`, `agent/config.py` | One LLM wrapper with rate-limit retries; one place for settings. |

## Important design decisions

- **browser-use is the hands, not the brain.** It handles clicking, typing and reading pages. Planning, approvals, retry policy, memory and verification are my own code, because the assignment is about reliability and verification, not about calling a library.
- **The verifier does not use the LLM and does not trust the agent.** It reads the vendor page with HTTP and regex and reads the ERP through a JSON API the browser agent is never told about. A model cannot both do the work and certify it.
- **Ground truth beats claims inside the loop too.** A write step counts as done only if a new record actually exists in the ERP, regardless of what the operator says.
- **Generalization through data, not code.** Nothing in `agent/` mentions Company X or invoices as a special case, and tasks are plain text. Company knowledge lives in `company_context.yaml`. (The verifier does know the invoice/ERP *domain*; a different domain needs a different verifier, see limitations.)
- **Approval before writes, always visible.** The user sees the exact values about to be written.
- **Idempotency.** Before writing, the runner checks whether the record already exists, so running the same task twice never creates a duplicate.
- **Learning from mistakes.** When the ERP rejects an entry, the error messages are saved to `lessons.json` and given to the planner and the operator on later runs, so the second run avoids the first run's mistakes. Run `--clear-lessons` to see the difference.
- **Narrow sub-goals and small prompts.** Each step sends only the facts it needs, which keeps token use low and works better with rate-limited free tiers.

## Models, APIs and components used

- **LLM:** your choice via `.env` (Gemini, OpenAI, Anthropic or Groq). The same model object plans and drives the browser. *(Fill in the exact model you used for your demo.)*
- **browser-use** (open source): browser control and page reading.
- **Flask**: the sandbox company app. **PyYAML**, **python-dotenv**: configuration. **pytest**: tests.
- AI coding tools were used to help write this project; I can explain and modify every part.

## Assumptions

- Everything runs on `localhost` against the sandbox. No real credentials, company data or third-party systems.
- "Latest invoice" means the most recently issued non-draft invoice (stated in `company_context.yaml`).
- A human is available at the terminal to approve writes and answer questions.

## Known limitations

- The verifier is specific to the invoice-to-ERP workflow. A new workflow needs a new check (the loop itself is unchanged).
- Browser control quality depends on the LLM. Small or rate-limited models can loop or misread pages, and the free tiers of some providers are too small for multi-step runs.
- Writes are limited to one invoice per task. Batch tasks ("add all overdue invoices") are not implemented.
- The browser operator is told to stay on the sandbox sites but this is not hard-enforced with a domain allow-list.
- The ERP has no edit or delete form, so a wrong entry is reported as a FAILED verification rather than repaired.
- Human interaction is a terminal prompt only.
- Evidence is the last screenshot of each attempt, not a full recording.

## What I would build next

1. Hard domain allow-listing and per-action permissions for the browser.
2. Batch tasks with per-item verification and partial-failure handling.
3. A pluggable verifier interface, so each workflow registers its own ground-truth check.
4. Chaos testing (random server errors, session expiry, UI changes) and an evaluation runner that reports pass rates across many runs.
5. A repair step: when verification fails, plan and run a correction automatically.
6. A web UI for approvals and run history, and background execution with a task queue.

## Results from my own runs

*(Fill this table in after running the tasks yourself. Do not leave invented numbers.)*

| Task | Model | Attempts / steps | Human interventions | Verification | Notes |
|---|---|---|---|---|---|
| 1. Enter latest Company X invoice | | | | | |
| 2. Earliest unpaid invoice, Company Y | | | | | |
| 3. Enter latest Company Y invoice | | | | | |
| 4. Task 1 again (duplicate) | | | | | |
| 5. No vendor named (asks the human) | | | | | |

## What the offline tests cover

`python -m pytest -q` covers the checker's pure logic (amount and date normalization, page parsing, comparison). The full loop was also exercised against the live sandbox with a stand-in for the LLM and browser, covering: self-correction after ERP errors and lesson saving, duplicate skipping, a wrong amount caught by the verifier, a false "done" rejected by the ground-truth check, a rejected approval, and a read-only task. Real LLM + browser runs are what the table above is for.

## Demo video script (about 5 minutes)

1. Show `http://localhost:5050/vendor` and point out the draft invoice trap and the ERP's strict form.
2. `python run.py --clear-lessons` then `python run.py --reset-erp`. Run `python run.py --task 1`. Show the plan, the approval prompt, the retry or self-correction if it happens, and the VERIFIED result. Open `/erp` to show the saved bill.
3. Run `python run.py --task 1` again. Show it **skipping the duplicate** and still verifying.
4. Run `python run.py --reset-erp`, then `--task 1` again. Show the **lessons** from run 1 making this run smoother.
5. Run `--task 2` (read-only) and `--task 5` (it asks which vendor).
6. Open `runs/<id>/report.md` and `audit.jsonl` and explain how to trace why the agent made each decision.
