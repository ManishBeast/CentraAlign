"""
Verifier: decides whether the work was REALLY done.

It never trusts the browser agent's "done". It re-reads the source (vendor portal page)
with plain HTTP + regex and compares it to what the ERP actually saved (read from the
ERP's JSON API, which the browser agent is never told about).
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from agent import config

DATE_FORMATS = ("%b %d, %Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%B %d, %Y")


# ---------------- plain helpers (unit-tested) ----------------
def to_float(value):
    """'$2,450.75' -> 2450.75. Returns None if there is no number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def norm_date(value):
    """Any common date format -> 'DD-MM-YYYY'. Returns None if it cannot be read."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return None


def parse_invoice_page(html):
    """Read vendor, amount, due date and status out of a vendor-portal invoice page."""
    def grab(pattern):
        m = re.search(pattern, html)
        return m.group(1).strip() if m else None

    vendor = grab(r"Vendor:\s*([^<]+)")
    amount = to_float(grab(r"Total:\s*([^<]+)"))
    due = norm_date(grab(r"Due date:\s*([^<]+)"))
    status = grab(r"Status:\s*([^<]+)")
    if vendor is None or amount is None or due is None:
        return None
    return {"vendor": vendor, "amount": amount, "due_date": due, "status": (status or "").lower()}


def compare(record, source):
    """Compare an ERP bill to the source invoice. Returns a list of problems (empty = match)."""
    problems = []
    if record.get("vendor") != source["vendor"]:
        problems.append(f"vendor: ERP has '{record.get('vendor')}', source says '{source['vendor']}'")
    rec_amount = to_float(record.get("amount"))
    if rec_amount is None or abs(rec_amount - source["amount"]) > 0.005:
        problems.append(f"amount: ERP has {record.get('amount')}, source says {source['amount']:.2f}")
    if norm_date(record.get("due_date")) != source["due_date"]:
        problems.append(f"due date: ERP has {record.get('due_date')}, source says {source['due_date']}")
    return problems


def invoice_numbers_from(facts):
    """Which invoice(s) does this run claim to have handled?"""
    nums = []
    one = facts.get("invoice_number")
    many = facts.get("invoice_numbers")
    if isinstance(one, str) and one.strip():
        nums.append(one.strip())
    if isinstance(many, list):
        nums.extend(str(n).strip() for n in many if str(n).strip())
    return list(dict.fromkeys(nums))  # remove duplicates, keep order


# ---------------- network helpers ----------------
def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_bills():
    """Ground truth: everything the ERP has saved."""
    return json.loads(_get(f"{config.APP_URL}/erp/api/bills"))["bills"]


def fetch_source(invoice_number):
    """Read an invoice straight from the vendor portal. None if it does not exist."""
    try:
        return parse_invoice_page(_get(f"{config.APP_URL}/vendor/invoice/{invoice_number}"))
    except urllib.error.HTTPError:
        return None


# ---------------- the main check ----------------
def verify(before, after, facts, expect_write):
    """
    before / after : ERP bills before and after the run
    facts          : what the agent says it found/entered
    expect_write   : True if the plan was meant to change the ERP
    Returns {"verdict": VERIFIED | FAILED | UNVERIFIABLE, "checks": [{name, ok, detail}]}
    """
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    before_ids = {b["id"] for b in before}
    new_bills = [b for b in after if b["id"] not in before_ids]
    claimed = invoice_numbers_from(facts)

    # 1. side effects
    if not expect_write:
        check("Read-only task made no ERP changes", len(new_bills) == 0,
              f"{len(new_bills)} new bill(s) appeared" if new_bills else "")
    else:
        unexpected = [b["invoice_number"] for b in new_bills if b["invoice_number"] not in claimed]
        check("No unintended ERP records created", not unexpected,
              f"unexpected: {unexpected}" if unexpected else "")

    # 2. duplicates
    numbers = [b["invoice_number"] for b in after]
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    check("No duplicate invoice numbers in ERP", not dupes, f"duplicates: {dupes}" if dupes else "")

    # 3. every invoice the agent claims to have handled
    if not claimed:
        return {"verdict": "UNVERIFIABLE", "checks": checks
                + [{"name": "Agent reported an invoice number", "ok": False, "detail": "nothing to verify against"}]}

    for inv in claimed:
        source = fetch_source(inv)
        if source is None:
            check(f"{inv}: exists on vendor portal", False, "invoice not found on the portal")
            continue
        check(f"{inv}: exists on vendor portal", True)

        if expect_write:
            check(f"{inv}: is not a draft", source["status"] != "draft", f"status is '{source['status']}'")
            records = [b for b in after if b["invoice_number"] == inv]
            check(f"{inv}: saved in ERP exactly once", len(records) == 1, f"found {len(records)}")
            if len(records) == 1:
                problems = compare(records[0], source)
                check(f"{inv}: ERP values match the vendor page", not problems, "; ".join(problems))
        else:
            # read-only: check the numbers the agent REPORTED against the source
            problems = []
            if facts.get("amount") not in (None, "") and to_float(facts["amount"]) is not None:
                if abs(to_float(facts["amount"]) - source["amount"]) > 0.005:
                    problems.append(f"amount reported {facts['amount']}, source says {source['amount']:.2f}")
            if facts.get("due_date") and norm_date(facts["due_date"]):
                if norm_date(facts["due_date"]) != source["due_date"]:
                    problems.append(f"due date reported {facts['due_date']}, source says {source['due_date']}")
            check(f"{inv}: reported answer matches the vendor page", not problems, "; ".join(problems))

    verdict = "VERIFIED" if all(c["ok"] for c in checks) else "FAILED"
    return {"verdict": verdict, "checks": checks}
