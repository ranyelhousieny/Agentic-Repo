---
description: "Template for a new Claude Code skill. Skills auto-activate based on triggers (file imports, keywords, file patterns) — different from slash commands which require explicit /invocation."
template_version: 0
status: pre-battle-tested
---

# {SKILL_NAME} Skill

> **This is a template.** Replace `{SKILL_NAME}`, `{DOMAIN_DESCRIPTION}`, the triggers, and the procedure. Strip inline `<!-- WHY -->` annotations before publishing.

## What this skill does

{ONE_PARAGRAPH_DESCRIPTION — what domain this skill covers and what value it adds. Example: "Build, debug, and optimize {DOMAIN} apps. Apps built with this skill should follow {KEY_PATTERN}."}

## Trigger when

<!-- WHY: Skills should auto-activate when relevant. Be SPECIFIC about triggers
     so the skill doesn't fire on unrelated work. Be specific about SKIPS too. -->

- {File imports} — e.g., code imports `{specific-package}`
- {Keywords in user prompt} — e.g., user mentions `{specific-domain-term}`
- {File-name patterns} — e.g., filename matches `{specific-pattern}`
- {Specific user actions} — e.g., user adds/modifies a `{specific-feature}`

## Skip when

- {File imports a different framework} — e.g., file imports `{competing-package}`
- {File-name patterns that look similar but aren't} — e.g., `*-other.py`
- {Provider-neutral or unrelated code}
- {General programming/{adjacent-domain} questions}

## Procedure (the actual skill content)

When activated, follow this procedure:

1. {First step — usually a state check or context gather}
2. {Second step — main action}
3. {Third step — verification}

{Add as many steps as needed. Each step should have a clear pass/fail criterion.}

### Anti-patterns (do NOT do)

- {Common mistake 1}
- {Common mistake 2}
- {Failure mode that the procedure exists to prevent}

## Critical rules

1. **Auto-activation must be unambiguous.** A skill that fires on unrelated work is worse than no skill — the user loses trust.
2. **Skills don't replace expert agents.** Skills are reusable procedures; agents are role-and-context-bearing personas. If the work needs a sustained role, use an agent template instead.
3. **Document the WHY of every trigger and skip.** Future-you (or another fork-er) needs to understand why these specific triggers were chosen.

## Battle-tested in

<!-- TODO when instantiating: replace with 1-3 real projects where this skill has been applied. Use generic descriptors only — no employer or client identifiers. Until first use, leave as `(not yet battle-tested)`. -->

(not yet battle-tested)

---

## Why this template exists (delete from your published skill file)

Claude Code skills auto-activate based on context (file imports, prompt keywords, file patterns) — different from slash commands which require `/explicit-invocation`. The conventions encoded here came from running 50+ skills and discovering:

1. **Trigger specificity matters more than skill content.** A great skill that fires on the wrong work is net-negative. Spend the time to write tight TRIGGER and SKIP rules.
2. **Auto-activation noise erodes trust fast.** Once a user has dismissed a skill twice for over-firing, they won't activate it again. Better to under-fire and have the user invoke manually.
3. **Skills should be small, single-purpose.** If you find yourself writing >300 lines of procedure, you probably want an agent template instead.
4. **Anti-patterns ARE part of the skill.** Listing common mistakes prevents the AI from making them on autopilot.

References:

**Original work this template draws from (Rany ElHousieny):**
- The Agentic Repos framework (open source): https://github.com/ranyelhousieny/Agentic-Repo
- Building an AI-Powered Markdown Knowledge Base — Medium, Apr 2026: https://medium.com/cwan-engineering/building-an-ai-powered-markdown-knowledge-base-system-for-your-engineering-team-4bccea3cdbfe
- LinkedIn: https://linkedin.com/in/rany-ai/
