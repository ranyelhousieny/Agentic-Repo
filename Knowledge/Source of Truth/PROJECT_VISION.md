# Agentic-Repos Framework - Project Vision

**Status:** ACTIVE
**Authority:** Source of Truth (READ ONLY once finalized)
**Last Updated:** April 8, 2026
**Author:** Rany Elhousieny

---

## Project Mission

Transform any repository into an AI-powered agentic development environment. Give every developer, on any tech stack, the same AI-powered workflow that made the originating team 3x more productive.

## Strategic Goals

1. **One-command conversion** - A single command (`/project:convert-repo-to-agentic`) converts any repo regardless of tech stack
2. **Evidence-based AI** - Zero hallucination policy enforced in every generated artifact
3. **Session continuity** - AI never starts from scratch; progress is tracked and resumed
4. **Knowledge Graph navigation** - Structured navigation replaces blind codebase searching
5. **Multi-tool support** - Works with Claude Code AND Windsurf (and future tools)

## Success Criteria

- Any repo can be converted in under 5 minutes
- Generated artifacts are tailored to the detected tech stack
- Knowledge Graph accurately reflects all documents and their relationships
- Session logs enable seamless handoff between AI conversations
- Framework patterns validated in production

## Architecture Decisions

1. **Single Source of Truth pattern** - Agent prompts live in `prompts/templates/AI Agents/`; all other locations are thin wrappers
2. **Generated artifacts go to `Generated/`** - Never pollute source directories
3. **Knowledge hierarchy** - 4-tier authority system (Source of Truth > Framework > Generated > Templates)
4. **Tech stack detection via file presence** - Check for pom.xml, package.json, requirements.txt, etc. rather than guessing

## Provenance

Extracted from the production architecture of a large-scale API platform:
- 86+ Windsurf workflows
- 40+ specialized Claude agents
- 38 Claude Code commands
- 12+ months of daily AI-assisted development

## Out of Scope

- Runtime code execution or deployment
- IDE plugin development (uses existing Claude Code / Windsurf)
- Hosting or SaaS delivery
- Language-specific linting or formatting rules
