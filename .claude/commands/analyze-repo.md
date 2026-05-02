---
description: Deep analysis of any repository - tech stack, endpoints, auth patterns, tests, CI/CD. All findings cited with file:line evidence.
---

# Analyze Repo

Performs deep evidence-based analysis of a repository.

## Activation Steps

0. Run: `date '+%A, %B %d, %Y %H:%M %Z'`

1. Read `START_HERE.md`

2. Use the `repo-analyzer` agent to conduct the analysis.

3. The agent will:
   - Detect tech stack from actual files (not assumed)
   - Count and catalog all endpoints
   - Identify authentication patterns
   - Assess test coverage
   - Find CI/CD configuration
   - Identify architecture patterns

4. Save the analysis report to:
   `Generated/Analysis/YYYY-MM-DD_{repo-name}_analysis.md`

5. All findings cite file:line evidence.

## Usage

```
/project:analyze-repo
```

Then provide the repo path when prompted, or ask the agent about the current repo.
