---
description: Plan a change together - ask questions, measure on the data, agree what to do. No changes to the repo.
model: claude-opus-5-5
allowed-tools: Read, Grep, Glob, Bash
---
Planning mode. It stays on for the following messages too, until the user gives another mode command
(`/chat`, `/do`). The user's message:

$ARGUMENTS

- Answer in Russian, as CLAUDE.md says.
- Do not change the repo (code, tests, CLAUDE.md, main.py, reports). Scripts for measuring go to the scratchpad
  directory only, and they only read the project folders.
- Before proposing a check, measure it on all test projects: how many findings, real examples, false findings.
  Give numbers, not guesses. Say clearly what was not measured.
- Follow CLAUDE.md: the multilingual hard rule, no project folder names or language names in the repo.
- Ask only questions whose answer changes what will be built; give a recommendation for each.
- End with a short plan: what will change, what is decided, what is still open. The user starts the work with `/do`.
