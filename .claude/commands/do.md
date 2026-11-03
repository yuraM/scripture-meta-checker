---
description: Make the agreed changes - code, tests, CLAUDE.md, reports.
model: claude-opus-5-5
---
Work mode. It stays on for the following messages too, until the user gives another mode command
(`/chat`, `/planning`). The user's message:

$ARGUMENTS

- Do what was agreed in the plan (this conversation) and in this message. If something important is not agreed,
  ask before changing it; small technical choices you make yourself and name in the summary.
- Follow CLAUDE.md: coding conventions, multilingual hard rule, simple English in reports, no project folder names
  or language names in the repo.
- A new or changed check needs: a test, a row in the CLAUDE.md table, a description in `CHECK_DESCRIPTIONS`,
  and a line in `CHECKS` in `main.py`.
- When done: run `.venv/Scripts/python.exe -m unittest`, run the changed checks on all test projects
  (`main.py <project> --checks ... --unique --report-dir <project>_report`), compare with the numbers before,
  and look at real findings for false ones.
- Answer in Russian: what changed, the numbers per project, what is still open.
