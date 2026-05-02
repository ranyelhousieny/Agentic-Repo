---
description: Generate a session context log for continuity. Captures what was accomplished, current state, decisions made, and next steps so the next AI session picks up exactly where this one left off.
---

# Generate Session Context

Creates a session continuity log so the next AI conversation starts with full context.

## Activation Steps

0. Run: `date '+%A, %B %d, %Y %H:%M %Z'`

1. Review what was done in this session by reading the conversation history.

2. Create a session log saved to:
   `Generated/session_logs/YYYY-MM-DD_{topic}_session.md`

3. The log MUST include:
   - **Session Summary**: What was accomplished (3-5 bullets)
   - **Current State**: Where things stand right now (in-progress work)
   - **Key Decisions**: Any decisions made with rationale
   - **Next Steps**: Top 3 priorities for next session (be specific)
   - **Blockers**: Any open questions or blockers
   - **Files Modified**: List of files created or changed
   - **Commands to Run Next**: Specific commands ready to paste

4. Update `Generated/PROGRESS_TRACKER.md` with:
   - Today's accomplishments
   - Updated next steps

5. The next session should START by reading this log.

## What Not To Include

- Do NOT write a transcript of the conversation
- Do NOT repeat things that are already in `START_HERE.md`
- Focus on: "What does the NEXT session need to know to continue effectively?"
