"""
Command line:
  python run.py "Find the latest invoice from Company X and enter it into our internal system"
  python run.py --task 1            (run a task from tasks.yaml)
  python run.py --list              (show the tasks)
  python run.py --reset-erp         (empty the ERP bills)
  python run.py --clear-lessons     (forget what the agent learned)
Add --auto-approve to skip the "Approve? [y/N]" question (for testing only).
"""
import argparse
import asyncio
import json
import sys

import yaml

from agent import config, memory


def load_tasks():
    return yaml.safe_load((config.ROOT / "tasks.yaml").read_text())["tasks"]


def main():
    p = argparse.ArgumentParser(description="OpsPilot: an autonomous task worker")
    p.add_argument("task", nargs="?", help="the task in plain English")
    p.add_argument("--task", dest="task_no", type=int, help="run task number N from tasks.yaml")
    p.add_argument("--list", action="store_true", help="list the tasks in tasks.yaml")
    p.add_argument("--auto-approve", action="store_true", help="skip the write-approval question")
    p.add_argument("--reset-erp", action="store_true", help="empty all ERP bills")
    p.add_argument("--clear-lessons", action="store_true", help="forget saved lessons")
    a = p.parse_args()

    if a.list:
        for i, t in enumerate(load_tasks(), 1):
            print(f"{i}. {t}")
        return
    if a.reset_erp:
        config.ERP_FILE.write_text(json.dumps({"bills": []}, indent=2))
        print("ERP bills cleared.")
        return
    if a.clear_lessons:
        memory.clear_lessons()
        print("Lessons cleared.")
        return

    task = a.task
    if a.task_no:
        tasks = load_tasks()
        if not 1 <= a.task_no <= len(tasks):
            sys.exit(f"Task number must be 1..{len(tasks)}")
        task = tasks[a.task_no - 1]
    if not task:
        p.print_help()
        return

    from agent.runner import run_task  # imported here so --list / --reset-erp work without an LLM key
    asyncio.run(run_task(task, auto_approve=a.auto_approve))


if __name__ == "__main__":
    main()
