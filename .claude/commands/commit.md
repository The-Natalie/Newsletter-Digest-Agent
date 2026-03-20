# /commit

## Purpose
Create a standardized commit message that helps future `/prime` runs reconstruct project history.

## Instructions
- Create a new commit for all uncommitted changes.
- Run `git status && git diff HEAD && git status --porcelain` to see what files are uncommitted.
- Add the untracked and changed files.
- Add an atomic commit message with an appropriate message.
- Add a tag such as `feat`, `fix`, `docs`, etc. that reflects the work.

## Format
`type(scope): summary`

## Body
Include:
- what changed
- why it changed
- validation performed

## Rules
- Mention the feature or phase explicitly.
- Mention key tests or checks that passed.
- Keep it readable and specific.
