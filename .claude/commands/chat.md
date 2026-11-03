---
description: Talk about the project - questions, reports, findings. No changes to files.
model: claude-sonnet-5-5
allowed-tools: Read, Grep, Glob
---
Chat mode. It stays on for the following messages too, until the user gives another mode command
(`/planning`, `/do`). The user's message:

$ARGUMENTS

- Answer in Russian, as CLAUDE.md says. Keep it short and plain.
- Only read: reports, project files, code. Do not create, edit or delete files and do not run the checker.
- If the answer needs measuring on the data or a decision about a change, say so and suggest `/planning`.
- If the user asks to change something, suggest `/do` (after `/planning` if the change is not agreed yet).
