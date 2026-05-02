# Agentic-Repos Framework - Windsurf Rules

**CRITICAL: These rules apply to ALL AI interactions in this workspace.**

**Synced from:** CLAUDE.md (same rules, Windsurf format)
**Last Updated:** April 7, 2026

---

## SESSION STARTUP (MANDATORY - DO THIS FIRST)

At the start of each session:
```
Read START_HERE.md to understand the framework. Then read Knowledge/KNOWLEDGE_GRAPH.md for navigation. Summarize the current focus and ask how to help.
```

---

## ZERO HALLUCINATION POLICY

Every claim must be verifiable. Uncertainty must be explicit. No speculation.

---

## Rule 0: Session Initialization

1. `START_HERE.md` - Framework overview
2. `Knowledge/KNOWLEDGE_GRAPH.md` - Navigation map
3. `Generated/PROGRESS_TRACKER.md` - Where we left off

---

## Rule 1: Evidence-Based Responses

Every factual claim cites: file:line, URL, or command output.

If you cannot cite a source: say "I need to verify this."

---

## Rule 2: Explicit Uncertainty

Use these phrases when uncertain:
- "I am not certain - please verify"
- "This needs confirmation from [source]"
- "I cannot find authoritative evidence for this claim"

Confidence levels: HIGH | MEDIUM | LOW

---

## Rule 3: No Speculation

Forbidden: guessing configs, endpoints, or system behavior without evidence.

---

## Rule 4: Source of Truth

`Knowledge/Source of Truth/` is READ ONLY. Never modify. Always wins in conflicts.

---

## Rule 5: Technical Claims Format

```
CLAIM: [Statement]
SOURCE: [file:line or URL]
CONFIDENCE: HIGH | MEDIUM | LOW
VERIFIED: [date or "Not yet verified"]
```

---

## Rule 6: Agent Architecture

Source prompts: `prompts/templates/AI Agents/`
Workflows here are thin wrappers. Never duplicate agent content.

---

## Rule 7: Knowledge Graph Navigation

Search order:
1. `Knowledge/KNOWLEDGE_GRAPH.md`
2. `Knowledge/DOCUMENT_INDEX.md`
3. Full-text grep (last resort)

When adding documents: update both KNOWLEDGE_GRAPH.md and DOCUMENT_INDEX.md.

---

## Rule 8: Generated Artifacts

ALL AI output → `Generated/` directory.
Do NOT save to root, Knowledge/, or prompts/.

---

## Rule 9: .env Parsing

ALWAYS: `cut -d'=' -f2-` (trailing dash)
NEVER: `cut -d'=' -f2` (truncates at embedded `=`)

---

## Primary Workflow

`/convert-repo-to-agentic` - Transform any repo into an agentic environment.
