---
description: Execute an implementation plan
argument-hint: [path-to-plan]
---

## Execution Log Capture

Create the execution report file before starting any tasks.

Write the full verbatim output of the entire execution to `.agents/execution-reports/<timestamp>-<plan-name>.md` as you go — every command run, every line of test output, every validation result exactly as printed, every deviation or issue encountered.

Do not summarize. Do not shorten. Do not omit anything.

In the terminal, only print:
- the path to the report file
- a one-line status (e.g. "34/34 tests passing, ready for /commit")

---

# Execute: Implement from Plan

## Plan to Execute

Read plan file: `$ARGUMENTS`

Use the approved feature plan as the source of truth. Load the relevant code files and only the supporting reference docs required for the current task.

## Execution Instructions

### 1. Read and Understand

- Read the ENTIRE plan carefully
- Understand all tasks and their dependencies
- Note the validation commands to run
- Review the testing strategy

### 2. Execute Tasks in Order

For EACH task in "Step by Step Tasks":

#### a. Navigate to the task
- Identify the file and action required
- Read existing related files if modifying

#### b. Implement the task
- Follow the detailed specifications exactly
- Maintain consistency with existing code patterns
- Include proper type hints and documentation
- Add structured logging where appropriate
- Implement in small, reviewable steps
- Do not widen scope beyond the plan unless you explicitly call it out

#### c. Verify as you go
- After each file change, check syntax
- Ensure imports are correct
- Verify types are properly defined

### 3. Implement Testing Strategy

After completing implementation tasks:

- Create all test files specified in the plan
- Implement all test cases mentioned
- Follow the testing approach outlined
- Ensure tests cover edge cases

### 4. Run Validation Commands

Execute ALL validation commands from the plan in order:

```bash
# Run each command exactly as specified in plan
```

If any command fails:
- Fix the issue
- Re-run the command
- Continue only when it passes
- If a blocker cannot be resolved safely, stop and surface it rather than inventing around it

### 5. Final Verification

Before completing:

- ✅ All tasks from plan completed
- ✅ All tests created and passing
- ✅ All validation commands pass
- ✅ Code follows project conventions
- ✅ Documentation added/updated as needed

## End of Report Checklist

At the end of the execution report file, append:

```
## Ready for Commit

- [ ] All tasks completed
- [ ] All validation commands passed
- [ ] All tests passing

## Follow-up Items

- (any deviations, edge cases, or items deferred from this execution)
```

## Notes

- If you encounter issues not addressed in the plan, document them
- If you need to deviate from the plan, explain why
- If tests fail, fix implementation until they pass
- Don't skip validation steps