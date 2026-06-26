---
name: check-3x
description: Use when completing any coding task. After finishing work, check every detail 3 times, then run the logic in a venv or docker to verify it works. If the output is fine, mark the task complete. If not, go back and fix the issues before finishing.
---

# Triple-Check Before Finishing

Use this skill whenever a task is completed. Follow these steps **every time** before marking work as done:

## 1. First Check — Logic Review

- Read through every file you changed
- Verify imports, variable names, types, and logic are correct
- Confirm the code matches the original requirements

## 2. Second Check — Edge Cases

- Look for null/undefined handling
- Check boundary conditions
- Verify error handling paths exist

## 3. Third Check — Full Run

- Set up a Python virtual environment (or use Docker if the project uses it)
- Install dependencies
- Run the actual code or tests
- If the output is **correct**, the task is done
- If the output is **wrong or errors**, go back and fix the issues, then restart from Step 1

## Flow

```
Complete work
    → Check 1 (logic review)
    → Check 2 (edge cases)
    → Check 3 (run in venv/docker)
        → Pass: DONE
        → Fail: fix issues → restart from Check 1
```

## Requirements

- Never skip the run step. A visual review alone is not enough.
- If the project has tests, run them as part of Check 3.
- If the project uses Docker, use Docker instead of a local venv.
- Only declare success after Check 3 passes.
