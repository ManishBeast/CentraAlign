"""
Fake company website for the agent to practice on.
  /vendor         -> vendor portal: where invoices are found
  /erp            -> internal system: where bills must be entered
  /erp/api/bills  -> read-only JSON, used ONLY by our checker (never by the browser agent)

Run:   python app.py --reset      (--reset empties the ERP first)
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)
DB = Path(__file__).parent / "erp_data.json"  # the ERP's saved bills live here

VENDORS = {"x": "Company X", "y": "Company Y", "z": "Company Z"}

# TRAP 1: INV-1007 is a DRAFT that looks newest. The real latest invoice is INV-1004.
INVOICES = [
    {"number": "INV-1001", "vendor": "x", "amount": 1200.50, "issued": "2026-07-01", "due": "2026-07-31", "status": "paid"},
    {"number": "INV-1004", "vendor": "x", "amount": 2450.75, "issued": "2026-08-15", "due": "2026-09-14", "status": "unpaid"},
    {"number": "INV-1007", "vendor": "x", "amount": 980.00, "issued": "2026-09-20", "due": "2026-10-20", "status": "draft"},
    {"number": "INV-3001", "vendor": "y", "amount": 310.00, "issued": "2026-09-01", "due": "2026-10-30", "status": "unpaid"},
    {"number": "INV-3002", "vendor": "y", "amount": 150.25, "issued": "2026-09-10", "due": "2026-10-12", "status": "unpaid"},
    {"number": "INV-3003", "vendor": "y", "amount": 725.00, "issued": "2026-09-18", "due": "2026-11-05", "status": "paid"},
    {"number": "INV-4001", "vendor": "z", "amount": 410.00, "issued": "2026-08-01", "due": "2026-08-30", "status": "overdue"},
    {"number": "INV-4002", "vendor": "z", "amount": 1875.40, "issued": "2026-08-10", "due": "2026-09-05", "status": "overdue"},
]


def load():
    if not DB.exists():
        save({"bills": []})
    return json.loads(DB.read_text())


def save(data):
    DB.write_text(json.dumps(data, indent=2))


CSS = """{% raw %}<style>
:root{--bg:#0b0d17;--panel:#12152a;--card:#181c34;--line:#262b4d;--txt:#e8eaf8;--mut:#8a90b8;--acc:#7c8cff;--acc2:#b07cff;--ok:#3ecf8e;--bad:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 60% -10%,#1b1f45 0%,var(--bg) 60%) fixed;color:var(--txt);font-family:Inter,system-ui,sans-serif;min-height:100vh}
.top{display:flex;justify-content:space-between;align-items:center;padding:14px 28px;border-bottom:1px solid var(--line);background:rgba(18,21,42,.85)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px}
.logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--acc2));display:grid;place-items:center;font-size:16px}
nav{display:flex;gap:6px}
nav a{color:var(--mut);text-decoration:none;padding:7px 14px;border-radius:9px;font-size:14px;font-weight:600}
nav a:hover{color:var(--txt);background:var(--card)}
.wrap{max-width:860px;margin:28px auto;padding:0 20px}
h1{font-size:26px;margin:0 0 18px}
a{color:var(--acc)}
ul{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
li{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
li:hover{border-color:var(--acc)}
li a{text-decoration:none;font-weight:600;font-size:16px;display:block}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:14px}
th{background:#1d2142;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;text-align:left}
th,td{border:0!important;border-bottom:1px solid var(--line)!important;padding:11px 14px!important;font-size:14px}
tr:last-child td{border-bottom:0!important}
tr:hover td{background:#1d2142}
p{line-height:1.6}
form{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;max-width:460px}
form p{margin:0 0 14px;color:var(--mut);font-size:13px}
input,select{display:block;width:100%;margin-top:6px;padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:#0a0c18;color:var(--txt);font:inherit}
input:focus,select:focus{outline:0;border-color:var(--acc)}
button{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;border:0;border-radius:10px;padding:10px 20px;font-weight:600;cursor:pointer}
[style*="e6ffed"]{background:#12382a!important;color:var(--ok);border:1px solid #1d5a42;border-radius:10px;padding:10px 14px!important}
[style*="fde8e8"]{background:#3b1a1a!important;color:var(--bad);border:1px solid #5a2a2a;border-radius:10px;padding:10px 14px!important}
</style>{% endraw %}"""


def page(body, **ctx):
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Sandbox Company</title>' + CSS + '</head><body>'
        '<header class="top"><div class="brand"><span class="logo">&#10022;</span>Sandbox Co</div>'
        '<nav><a href="/vendor">Vendor Portal</a><a href="/erp">Internal ERP</a>'
        '<a href="/agent">AI Agent</a></nav></header>'
        '<main class="wrap">' + body + '</main></body></html>'
    )
    return render_template_string(html, **ctx)


# ---------------- Vendor portal ----------------
@app.route("/")
def home():
    return redirect("/vendor")


@app.route("/vendor")
def vendor_list():
    body = ("<h1>Vendor Portal</h1><ul>{% for id, name in vendors.items() %}"
            "<li><a href='/vendor/{{ id }}'>{{ name }}</a></li>{% endfor %}</ul>")
    return page(body, vendors=VENDORS)


@app.route("/vendor/<vid>")
def vendor_invoices(vid):
    if vid not in VENDORS:
        return "Vendor not found", 404
    items = sorted([i for i in INVOICES if i["vendor"] == vid], key=lambda i: i["issued"], reverse=True)
    body = """<h1>{{ name }}: Invoices</h1>
    <table border="1" cellpadding="6"><tr><th>Invoice</th><th>Issued</th><th>Amount</th><th>Status</th></tr>
    {% for i in items %}<tr><td><a href="/vendor/invoice/{{ i.number }}">{{ i.number }}</a></td>
    <td>{{ i.issued }}</td><td>{{ '%.2f'|format(i.amount) }}</td><td>{{ i.status }}</td></tr>{% endfor %}</table>"""
    return page(body, name=VENDORS[vid], items=items)


@app.route("/vendor/invoice/<number>")
def invoice_detail(number):
    inv = next((i for i in INVOICES if i["number"] == number), None)
    if not inv:
        return "Invoice not found", 404
    # TRAP 2: this page shows "Sep 14, 2026" and "$2,450.75".
    # The ERP wants 14-09-2026 and 2450.75, so the agent has to convert.
    due = datetime.strptime(inv["due"], "%Y-%m-%d").strftime("%b %d, %Y")
    body = """<h1>Invoice {{ inv.number }}</h1><p>Vendor: {{ vendor }}</p>
    <p>Due date: {{ due }}</p><p>Total: {{ amount }}</p><p>Status: {{ inv.status }}</p>"""
    return page(body, inv=inv, vendor=VENDORS[inv["vendor"]], due=due, amount=f"${inv['amount']:,.2f}")


# ---------------- Internal ERP ----------------
@app.route("/erp")
def erp_home():
    bills = load()["bills"]
    body = """<h1>Internal ERP: Bills</h1>
    {% if saved %}<p style="background:#e6ffed;padding:8px">Bill saved: {{ saved }}</p>{% endif %}
    <p><a href="/erp/bills/new">New bill entry</a></p>
    <table border="1" cellpadding="6"><tr><th>ID</th><th>Vendor</th><th>Invoice</th><th>Amount</th><th>Due date</th></tr>
    {% for b in bills %}<tr><td>{{ b.id }}</td><td>{{ b.vendor }}</td><td>{{ b.invoice_number }}</td>
    <td>{{ b.amount }}</td><td>{{ b.due_date }}</td></tr>{% endfor %}</table>"""
    return page(body, bills=bills, saved=request.args.get("saved"))


def validate(form, bills):
    """The ERP's strict rules. The agent must discover them from the error messages."""
    errors = []
    if form.get("vendor") not in VENDORS.values():
        errors.append("Please choose a valid vendor.")
    number = form.get("invoice_number", "").strip()
    if not re.fullmatch(r"INV-\d{4}", number):
        errors.append("Invoice number must look like INV-1234.")
    elif any(b["invoice_number"] == number for b in bills):
        errors.append(f"Invoice number {number} already exists.")
    if not re.fullmatch(r"\d+\.\d{2}", form.get("amount", "").strip()):
        errors.append("Amount must have exactly 2 decimals and no $ or commas (example: 2450.75).")
    try:
        due = form.get("due_date", "").strip()
        if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", due):
            raise ValueError
        datetime.strptime(due, "%d-%m-%Y")
    except ValueError:
        errors.append("Due date must be in DD-MM-YYYY format.")
    return errors


@app.route("/erp/bills/new", methods=["GET", "POST"])
def erp_new_bill():
    data = load()
    form, errors = {}, []
    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate(form, data["bills"])
        if not errors:
            data["bills"].append({
                "id": len(data["bills"]) + 1,
                "vendor": form["vendor"],
                "invoice_number": form["invoice_number"].strip(),
                "amount": float(form["amount"]),
                "due_date": form["due_date"].strip(),
            })
            save(data)
            return redirect(f"/erp?saved={form['invoice_number'].strip()}")
    body = """<h1>New bill entry</h1>
    {% for e in errors %}<p style="background:#fde8e8;padding:8px">{{ e }}</p>{% endfor %}
    <form method="post">
      <p>Vendor <select name="vendor">{% for name in vendors.values() %}
        <option value="{{ name }}" {% if form.get('vendor') == name %}selected{% endif %}>{{ name }}</option>{% endfor %}</select></p>
      <p>Invoice number <input name="invoice_number" value="{{ form.get('invoice_number', '') }}"></p>
      <p>Amount <input name="amount" value="{{ form.get('amount', '') }}"></p>
      <p>Due date <input name="due_date" placeholder="DD-MM-YYYY" value="{{ form.get('due_date', '') }}"></p>
      <p><button type="submit">Save Bill</button></p>
    </form>"""
    return page(body, errors=errors, form=form, vendors=VENDORS)


@app.route("/erp/api/bills")
def erp_api():
    """Read-only data for our CHECKER. The browser agent must never use this."""
    return jsonify(load())


if __name__ == "__main__":
    if "--reset" in sys.argv:
        save({"bills": []})
        print("ERP data reset.")
    app.run(port=5050)  # port 5000 is used by macOS AirPlay, so we use 5050
