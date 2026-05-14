# CITADEL Project Skills

This directory holds **project-specific skill wrappers** that extend the base anthropic skills with CITADEL context.

## Base skills you should rely on (already installed)

| Base skill | When to invoke | Why for CITADEL |
|---|---|---|
| `anthropic-skills:master-backend-builder` | Any backend task — FastAPI, schemas, deployment, frontend↔backend wiring | We are about to rebuild the entire backend from scratch. This skill knows the full SaaS backend playbook. |
| `anthropic-skills:ui-ux-pro-max` (or `userSettings:ui-ux-pro-max`) | Any UI / UX decision — new screens, components, accessibility, animations | We have an established neo-brutalist language; this skill prevents drift and catches UX gaps. |
| `engineering:code-review` | Before declaring any non-trivial change done | Independent fresh-eye review against our rules. |
| `engineering:debug` | Behavior diverges from expected | Structured reproduce → isolate → diagnose → fix. |
| `engineering:system-design` | Designing module boundaries, data models, service architecture | Use alongside `backend-architect` agent. |
| `engineering:testing-strategy` | Designing the test plan for a new module | Calibrates pyramid + coverage + CI gates. |
| `design:accessibility-review` | Before shipping any new screen or major change | WCAG 2.1 AA audit. |
| `design:ux-copy` | When writing button labels, error messages, empty states | Civic platform — clear, calm, plain English. |
| `design:design-system` | Auditing CITADEL's design tokens / variants for consistency | Keeps the brutal language tight. |

## How to invoke
Use the `/skill` invocation in chat or let Claude auto-route. The base skills above are surfaced via available-skills listings in every session.

## When to create a project-specific skill
Create a new skill folder here only when:
- The workflow is **specific to CITADEL** (e.g. "scaffold a new ML module from a spec") and
- The workflow is **multi-step and reusable** across many sessions and
- A slash command isn't sufficient (slash commands are good for one-shot prompts; skills bundle prompts + reference docs)

If those don't all apply, prefer a slash command in `.claude/commands/` instead.

## Currently project-specific skills
_(none yet — slash commands cover what we need today)_

If we ever build one, follow the structure:
```
.claude/skills/<skill-name>/
└── SKILL.md            # frontmatter + instructions, references project rules and agents
```
