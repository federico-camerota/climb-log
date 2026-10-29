# climb-log · design

Design for a local web app that replaces the three training spreadsheets as the day-to-day
interface (logging, visualization, analysis, planning). The data stays in spreadsheets
(local `.xlsx` or Google Sheets).

**Status:** M1 (module framework + local storage) done, released as v0.1.0; M2, the Google
Sheets backend, in progress: contract tests and Google login done (`07-roadmap.md`). Last updated 2026-10-29.

## Read in this order
| File | What it covers |
|---|---|
| [00-current-state.md](00-current-state.md) | Inventory of the 3 workbooks: fields, rules, thresholds. **Parity checklist.** |
| [01-goals-and-scope.md](01-goals-and-scope.md) | Goals, non-goals, constraints |
| [02-architecture.md](02-architecture.md) | Components, stack, data flow, API, package layout |
| [03-module-framework.md](03-module-framework.md) | Config-driven modules: fields, derived values, rules, programs, views, evolution |
| [04-storage.md](04-storage.md) | Spreadsheet layout, xlsx and Google backends, validation, legacy import |
| [05-analytics.md](05-analytics.md) | Metrics, parity analyses, new analyses, recommendation engine |
| [06-ui.md](06-ui.md) | Pages and flows |
| [07-roadmap.md](07-roadmap.md) | Milestones M0–M6, testing strategy |
| [08-workflow.md](08-workflow.md) | How the project is developed: roles, PR workflow, git conventions, quality gates, data protection, working with Claude |
| [decisions.md](decisions.md) | Decision log (accepted / proposed) |
| [open-questions.md](open-questions.md) | Open questions with default answers |
| [modules/](modules/) | Draft module YAMLs: shoulder and fear of falling (Google). The complete modules are in [/modules/](../modules/): the climbing journal (D-056) and finger strength (local, D-059) |
| [mockups/](mockups/sheet-tabs.md) | Spreadsheet mock-ups (Wellbeing, finger Sets) as real .xlsx files + description and verification |

## Process
See [08-workflow.md](08-workflow.md); the binding short version for Claude is [/CLAUDE.md](../CLAUDE.md).

1. Review the design; settle the *proposed* decisions and the open questions.
2. Implement milestone by milestone (`07-roadmap.md`), updating the roadmap status and
   `decisions.md` as we go. If the implementation diverges from these docs, update the
   docs in the same change.
