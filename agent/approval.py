"""Human-in-the-loop: ask the user questions and get approval before anything is written."""


def ask_human(question):
    print("\n" + "=" * 62)
    print("  THE AGENT NEEDS YOUR INPUT")
    print("  " + question)
    print("=" * 62)
    return input("  Your answer > ").strip()


def approve_write(step, facts, auto_approve):
    """Show exactly what is about to be written, then ask. Returns True/False."""
    print("\n" + "=" * 62)
    print("  APPROVAL NEEDED: the agent wants to WRITE to a company system")
    print(f"  Action : {step['goal']}")
    shown = {k: v for k, v in facts.items() if k in ("vendor", "invoice_number", "amount", "due_date")}
    for k, v in (shown or facts).items():
        print(f"    {k:15}: {v}")
    print("=" * 62)
    if auto_approve:
        print("  (auto-approved because --auto-approve was used)")
        return True
    return input("  Approve? [y/N] > ").strip().lower() in ("y", "yes")
