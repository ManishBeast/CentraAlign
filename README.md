# OpsPilot: an autonomous AI task worker

OpsPilot takes a plain-English company request and completes it by operating a real browser, then proves the work was done instead of just saying so.

> *"Find the latest invoice from Company X, extract the amount and due date, enter it into our internal system, and tell me once it is done."*

Built for the CentrAlign AI engineering assignment (**AI Engineering Intern: Autonomous AI Task Worker**).

```
Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Report
```

What makes it more than "an LLM clicking around a browser":

- **It verifies independently.** A checker with no LLM in it re-reads the vendor page and the ERP's saved data and compares them field by field. The agent saying "done" counts for nothing.
- **It asks before it writes.** Every write to the company system needs human approval, and the approval shows the exact values about to be saved.
- **It asks when the request is ambiguous.** "Enter the latest invoice" with no vendor named gets a question back, not a guess.
- **It never duplicates.** Before writing, it checks whether the record already exists.
- **It survives rate limits.** A pool of models is tried in order; a model that hits a quota is benched and the next one takes over.
- **It leaves an audit trail.** Every plan, observation, retry, approval and verification check is written to disk.

## Demo

**Demo video (about 5 min):** [Watch here](https://drive.google.com/file/d/1ugB6FF9GdIPtgg5YRyUOeXaj6r5lMHmv/view?usp=sharing)

The video shows the agent entering a vendor invoice into the ERP, asking for approval before writing, skipping a duplicate, asking which vendor when the request is vague, and the independent verifier returning VERIFIED.

## Quick start

**Requirements:** Python 3.11+ (developed on 3.12, macOS), Google Chrome installed, and at least one LLM API key. Tested with `browser-use` 0.13.11.

```bash
git clone <your-repo-url> centralign && cd centralign
conda create -n opspilot python=3.12 -y && conda activate opspilot   # or any venv
pip install -r requirements.txt
cp .env.example .env        # then add at least one API key (see Configuration)
```

### Option A: Web UI (recommended for the demo)

```bash
python web.py
```

Open **http://localhost:5050/agent**. Type a task or pick one from *Demo tasks*, press **Run task**, and watch the live log. When the agent needs you, an approval or question box appears on the page.

`web.py` serves the sandbox company and the agent UI from one process, so do not also run `app.py`.

### Option B: Command line

```bash
# terminal 1: the sandbox company (leave running)
python app.py --reset

# terminal 2: the agent
python run.py --list                     # show the demo tasks
python run.py --task 1                   # run demo task 1
python run.py "Which unpaid invoice from Company Y has the earliest due date?"
```

| Command | What it does |
|---|---|
| `python run.py --task N` | Run task number N from `tasks.yaml` |
| `python run.py "<text>"` | Run any plain-English task |
| `python run.py ... --auto-approve` | Skip the approval prompt (testing only) |
| `python run.py --reset-erp` | Empty the ERP bills |
| `python run.py --clear-lessons` | Make the agent forget what it learned |
| `python app.py --reset` | Start the sandbox with an empty ERP |
| `python -m pytest -q` | Run the unit tests |

At any time, open **http://localhost:5050/erp** in a normal browser to see what is saved in the ERP.

## Configuration

All settings live in `.env` (never commit it; it is in `.gitignore`).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_CHAIN` | empty | Ordered fallback list of `provider:model` pairs, e.g. `gemini:gemini-flash-latest,groq:openai/gpt-oss-120b,openai:gpt-4.1-mini`. Entries whose API key is missing are skipped. |
| `LLM_PROVIDER` | `gemini` | Used only when `LLM_CHAIN` is empty. One of `gemini`, `openai`, `anthropic`, `groq`. |
| `LLM_MODEL` | provider default | Model for `LLM_PROVIDER` when `LLM_CHAIN` is empty. |
| `GEMINI_FALLBACK_MODELS` | empty | Extra Gemini models to try after the primary (only when `LLM_CHAIN` is empty). |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | empty | Provider keys. Add only the ones you use. |
| `LLM_VISION` | `false` | `true` only if your model can read screenshots (costs more tokens). |
| `HEADLESS` | `false` | `false` shows the browser window, which is what you want for a demo. |
| `MAX_BROWSER_STEPS` | `20` | Max browser actions the operator may take for one plan step. |
| `MAX_ATTEMPTS` | `3` | Attempts per plan step before the agent asks a human for a hint. |
| `APP_URL` | `http://localhost:5050` | Where the sandbox runs. |

Minimal `.env` example:

```
LLM_CHAIN=gemini:gemini-flash-latest,groq:openai/gpt-oss-120b,openai:gpt-4.1-mini
GOOGLE_API_KEY=your-key
GROQ_API_KEY=your-key
OPENAI_API_KEY=your-key
LLM_VISION=false
HEADLESS=false
```

Get keys from: [Google AI Studio](https://aistudio.google.com/apikey) (free tier), [Groq](https://console.groq.com/keys) (free tier, small limits), [OpenAI](https://platform.openai.com/api-keys), [Anthropic](https://console.anthropic.com).

Model names change often. If the log shows `404 ... no longer available`, remove that entry from `LLM_CHAIN`.

## How it works

```
 user request (CLI or web UI)
      |
      v
 [Planner]  company_context.yaml + lessons.json  ->  plan of 1-4 steps, each with a tool
      |          \__ ambiguous request? ask the human, then re-plan
      v
 for each step:
   [Policy gate]  write step: skip if the record already exists; otherwise ask the human to approve
      |
   [Executor]     hands ONE narrow sub-goal to browser-use (real Chrome) via the model pool
      |
   [Judge]        ground-truth check in code: did a new ERP record really appear?
      |           no -> retry with the failure fed back; after N attempts ask the human for a hint
   [Memory]       facts found are kept for later steps; ERP error messages become lessons
      |
      v
 [Verifier]  re-reads the vendor page (HTTP) and the ERP (JSON API), compares field by field
      |
      v
 [Reporter]  verdict + evidence + audit trail
```

### The three tools the planner can choose

| Tool | Meaning | Needs approval |
|---|---|---|
| `browser_read` | Look something up on a website and report facts. Changes nothing. | No |
| `browser_write` | Enter or change data in a system. | **Yes** |
| `ask_human` | Ask the user something that cannot be found on the sites. | n/a |

### Modules

| File | Responsibility |
|---|---|
| `agent/planner.py` | Turns the request into a plan. Validates it and rejects unknown tools or empty goals. |
| `agent/runner.py` | The main loop: approval, attempts, retries, escalation to the human, idempotency, memory, verification. |
| `agent/executor.py` | Builds a narrow task for browser-use (sites, facts, policies, lessons, last failure) and parses its JSON answer. Keeps one screenshot per attempt as evidence. |
| `agent/verifier.py` | Independent verification. No LLM. |
| `agent/memory.py` | Working memory for a run, company knowledge from `company_context.yaml`, and persistent lessons in `lessons.json`. |
| `agent/llm_pool.py` | Model fallback: tries models in order, benches a failing one, picks the next. |
| `agent/llm.py` | Plain LLM calls for the planner, with fallback and JSON extraction from messy replies. |
| `agent/config.py` | Reads `.env`, builds the model chain. |
| `agent/approval.py` | Terminal prompts for approvals and questions. The web UI replaces these functions. |
| `agent/reporter.py` | Audit log (`audit.jsonl`) and the final `report.md`. |
| `web.py` | Web UI and its API. Serves the sandbox too. |
| `app.py` | The sandbox company (vendor portal, ERP, ERP read-only API). |

### What a run produces

Each run writes `runs/<run-id>/`:

- `report.md`: status, plan, the independent checks (PASS/FAIL), collected facts and a timeline.
- `audit.jsonl`: one JSON line per decision. Event types: `start`, `plan`, `clarification_asked`, `clarification_answered`, `approval`, `skip_write`, `observation`, `retry`, `lesson_saved`, `human_input`, `human_hint`, `error`, `verification`.
- `evidence/step<N>_attempt<M>.png`: the last screenshot of each attempt.

To answer "why did the agent do X?", open `audit.jsonl`: the `plan` event shows what it intended, each `observation` shows what the operator reported and whether the judge accepted it, and `verification` shows the final checks.

## The sandbox company

Everything runs against a fake company on `localhost`. No real systems, credentials or data are involved.

| URL | What it is |
|---|---|
| `/vendor` | Vendor portal. Lists Company X, Y and Z and their invoices. |
| `/erp` | Internal system: list of saved bills and a "New bill entry" form. |
| `/erp/api/bills` | Read-only JSON of saved bills. **Used only by the verifier and the judge, never by the browser operator.** |
| `/agent` | The agent web UI (served by `web.py`). |

The sandbox has deliberate traps, so the agent has to be careful rather than lucky:

1. **A draft looks newest.** For Company X, `INV-1007` is a draft issued after the real latest invoice `INV-1004`. `company_context.yaml` states the policy that drafts are not real invoices.
2. **Format mismatch.** The invoice page shows `$2,450.75` and `Sep 14, 2026`. The ERP only accepts `2450.75` and `14-09-2026`, and rejects anything else with an error message (the form also requires an `INV-1234` invoice number and one of the listed vendors).
3. **Duplicates.** The ERP rejects an invoice number that already exists, and the agent checks first so it does not try.

## Verification: how "done" is decided

The verifier (`agent/verifier.py`) never uses the LLM and never trusts what the operator reports. It reads the invoice straight from the vendor portal with HTTP and regex, reads the ERP's saved bills from its JSON API, and runs these checks:

| Check | Applies to |
|---|---|
| Read-only task made no ERP changes | read tasks |
| No unintended ERP records were created | write tasks |
| No duplicate invoice numbers in the ERP | all |
| The invoice the agent claims exists on the vendor portal | all |
| The invoice is not a draft | write tasks |
| Saved in the ERP exactly once | write tasks |
| Vendor, amount and due date in the ERP match the vendor page (amounts and dates are normalised first) | write tasks |
| The answer the agent reported matches the vendor page | read tasks |

Verdicts: **VERIFIED** (every check passed), **FAILED** (something is wrong, for example a wrong amount was saved), **UNVERIFIABLE** (the agent reported nothing to check against) and **NOT COMPLETED** (the run stopped or errored before finishing).

The same principle applies inside the loop: a write step counts as successful only if a new bill really appears in the ERP, whatever the operator claims.

## Design decisions

- **browser-use is the hands, not the brain.** It clicks, types and reads pages. Planning, approvals, retry policy, memory, model fallback and verification are my own code, because this assignment is about reliability and verification, not about calling a library.
- **Narrow sub-goals.** Each plan step gives the operator one small job plus only the facts, policies and lessons it needs. Smaller prompts mean fewer tokens, fewer mistakes and better behaviour on rate-limited free tiers.
- **Separate verifier.** One model must not both do the work and certify it, so verification is plain code against ground truth.
- **Generalisation through data, not code.** Nothing in `agent/` special-cases a company or a vendor. Tasks are plain text and company knowledge lives in `company_context.yaml`. Pointing the agent at a different workflow means changing that file (and the verifier, see limitations).
- **Approval gate in code, not in the prompt.** A write cannot start until the runner has the human's yes. Telling the LLM "please ask first" would not be a guarantee.
- **Idempotency.** Writes are skipped if the record already exists, so running a task twice is safe.
- **Learning from mistakes.** When the ERP rejects an entry, its error messages are saved to `lessons.json` and given to the planner and the operator on later runs.
- **Model pool with cooldowns.** Rate limits (about 1 minute), exhausted quotas (6 hours) and dead models such as a retired model name or bad key (24 hours) are told apart and benched accordingly. For write steps, if a model fails mid-step the executor first checks whether the bill was already saved before trying another model, so a failure never causes a blind second write.
- **One process for sandbox and UI.** Simpler to run and demo, at the cost of the limitations listed below.

## Results from real runs

All runs below were on the real stack (browser-use 0.13.11, real Chrome, sandbox on localhost). The browser steps in all of them ran on `gemini-flash-lite-latest`. During these runs the first chain entries failed (`gemini-flash-latest` hit its free-tier quota with a 429; `gemini-2.5-flash` and `gemini-2.5-flash-lite` returned 404 "no longer available to new users"), and the pool moved down the chain automatically. Times include rate-limit waiting.

| Demo task | Run | Result | Time | Retries | Human involvement |
|---|---|---|---|---|---|
| 1. Latest Company X invoice, enter into ERP (3-step plan: read, write, confirm) | `20261010-151347` | **VERIFIED**: INV-1004, 2450.75, due 14-09-2026, saved once | 86.8 s | 0 | 1 approval |
| 2. Earliest unpaid Company Y invoice (read-only) | `20261010-150951` | **VERIFIED**: INV-3002, $150.25, due Oct 12, 2026 | 91.1 s | 0 | none |
| 2. (repeat) | `20261010-165213` | **VERIFIED**: same answer | 77.3 s | 0 | none |
| 4. Same enter task again (duplicate) | `20261010-152352` | **VERIFIED**: write correctly skipped, still one record | 36.8 s | 0 | none |
| 5. "Enter the latest invoice" (no vendor), answered "Company X" | `20261010-184654` | **VERIFIED**: asked which vendor, then entered INV-1004 | 126.0 s | 0 | 1 question, 1 approval |
| 5. (same task), answered "Y" | `20261010-184627` | **Error**: planner returned no steps, run stopped before touching anything | 14.9 s | n/a | 1 question |
| 3. Enter latest Company Y invoice | not run yet | n/a | n/a | n/a | n/a |

Honest notes on these results:

- **Recovery and learning have not been observed in a real run.** Retries and lessons are implemented, but in every real run the operator already converted the amount and date to the ERP's format before writing, so the ERP never rejected anything and `lessons.json` stayed empty.
- The failed run is kept in the table on purpose. See limitation 1.
- Each run is a single sample, not a pass rate.

## Testing

```bash
python -m pytest -q
```

`tests/test_verifier.py` has 6 unit tests for the verifier's pure logic: amount parsing, date normalisation, invoice-page parsing, comparison of an ERP record to the source, and extraction of the claimed invoice numbers.

Beyond that, I exercised the full loop (retry after ERP rejection, lesson saving, duplicate skipping, a wrong amount caught by the verifier, a false "done" rejected by the ground-truth judge, a rejected approval, a read-only task) using a scripted stand-in for the LLM and browser against the live sandbox. That harness is not part of this repo. The model pool and the web UI have no automated tests.

## Project layout

```
.
├── app.py                  sandbox company: vendor portal, ERP, ERP JSON API
├── web.py                  web UI (/agent) + API, serves the sandbox too
├── run.py                  command-line entry point
├── company_context.yaml    what the agent knows about the company: systems, procedures, policies
├── tasks.yaml              demo tasks in plain English
├── requirements.txt
├── .env.example
├── agent/
│   ├── planner.py          request -> validated plan
│   ├── runner.py           the main loop
│   ├── executor.py         one step in the browser via browser-use
│   ├── verifier.py         independent verification
│   ├── memory.py           run memory, company knowledge, lessons
│   ├── llm_pool.py         model fallback and cooldowns
│   ├── llm.py              planner LLM calls and JSON extraction
│   ├── config.py           settings from .env
│   ├── approval.py         human prompts
│   └── reporter.py         audit log and report.md
├── tests/test_verifier.py
└── runs/                   one folder per run (git-ignored)
```

Generated at runtime and git-ignored: `.env`, `erp_data.json`, `lessons.json`, `runs/`, `*.log`.

## Assumptions

- Everything runs on `localhost` against the sandbox. No real credentials, company data or third-party systems are used.
- "Latest invoice" means the most recently issued **non-draft** invoice, as stated in `company_context.yaml`.
- The invoice detail page is the source of truth for amount and due date.
- A human is available (terminal or web page) to approve writes and answer questions.
- One run at a time.

## Known limitations

1. **A vague answer to a clarification question can stop the run.** If the user answers "Y" to "which vendor?", the planner returns no steps and the run ends with "The planner produced no steps" instead of asking again. (Seen in run `20261010-184627`.)
2. **Recovery from ERP rejections is untested on the real stack** (see results notes).
3. **Model-pool error classification is coarse.** Messages such as "not found" or "does not exist" are treated as a dead model (24-hour cooldown), and a browser timeout is treated like a rate limit. A normal browsing error could therefore bench a working model.
4. **The web UI has no protection against cross-site requests.** Its endpoints accept requests from any web page open in the same browser, including `/api/run` with `auto: true`, which skips approval. It only listens on localhost and the agent can only reach the sandbox, but it should not be left running while browsing untrusted sites.
5. **The verifier is specific to the invoice-to-ERP workflow** and reads the sandbox's HTML with regular expressions, so it is coupled to the page layout. A new workflow needs a new verifier.
6. **The browser operator is told which sites it may use but is not hard-blocked** from others. The sandbox control pages (`/agent`, `/api/*`) are on the same origin it browses.
7. **Writes are limited to one invoice per task.** Batch tasks such as "add all overdue invoices" are not implemented.
8. **No repair step.** The ERP has no edit or delete form, so a wrong entry is reported as FAILED rather than corrected.
9. **Results depend on the LLM.** Small or rate-limited models can loop or misread pages, and free tiers are slow and can run out mid-run.
10. **Evidence is limited** to the last screenshot of each attempt, not a recording.

## What I would build next

1. Fix limitations 1 to 4 first: re-ask on unusable answers, classify errors precisely (rate limit vs quota vs dead model vs ordinary browser error), and require a same-origin or token check on the web API.
2. A failure-injection mode in the sandbox (server error on first save, session expiry, a renamed button, a PDF whose amount disagrees with the page) plus an evaluation runner that reports pass rates over many runs. This would also give real evidence for retries and lessons.
3. Hard domain allow-listing and per-action permissions for the browser.
4. A pluggable verifier interface, so each workflow registers its own ground-truth check.
5. Batch tasks with per-item verification and partial-failure handling.
6. A repair step: when verification fails, plan and run a correction.
7. Background execution with a task queue, run history in a database and richer evidence (video or step-by-step screenshots).

## Models, APIs and components used

| Component | Use |
|---|---|
| [browser-use](https://github.com/browser-use/browser-use) 0.13.11 (open source) | Browser control and page reading. Used as a library; not modified. |
| Google Gemini (`gemini-flash-lite-latest` for the real runs above; `gemini-flash-latest` first in the chain) | Planning and browser operation. |
| Groq (`openai/gpt-oss-120b`) and OpenAI (`gpt-4.1-mini`) | Configurable fallbacks in the model chain. Anthropic is also supported. |
| Flask | The sandbox company and the web UI/API. |
| PyYAML, python-dotenv | Company knowledge, tasks and configuration. |
| pytest | Unit tests. |
| Google Chrome | The browser that browser-use drives. |

AI coding assistants (Claude) were used to help build this project. I can explain every part and modify it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach the sandbox at http://localhost:5050` | Start it: `python web.py` or `python app.py --reset`. |
| `Address already in use` on port 5050 | `web.py` already serves the sandbox. Do not run `app.py` at the same time. |
| `ModuleNotFoundError: No module named 'browser_use'` | You are in the wrong Python environment. Activate the one where you ran `pip install -r requirements.txt`. |
| `PermissionError: ... ~/.config/browseruse` | Your `~/.config` folder is owned by root. Fix with `sudo chown -R $(whoami) ~/.config`, or set `BROWSER_USE_CONFIG_DIR` to a folder you own. |
| `429 RESOURCE_EXHAUSTED` / quota errors | Free-tier limit reached. Add more models to `LLM_CHAIN`, wait a minute, or use a paid key. |
| `404 ... no longer available to new users` | That model name has been retired. Remove it from `LLM_CHAIN`. |
| `401` / `Incorrect API key` | The key in `.env` is wrong or belongs to a different provider. Check there is one key per line, no quotes. |
| The agent stops with "planner produced no steps" | Known limitation 1. Rerun and answer with the full vendor name, e.g. `Company X`. |
