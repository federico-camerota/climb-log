# 08 · Workflow and project practices

How this project is developed. It is a personal tool, but it is run as a professional,
**public** open-source project. The owner (me) is in charge of every decision and reviews
everything; Claude proposes and implements. The short, binding version of these rules for
Claude lives in `/CLAUDE.md`.

## 1. Roles and ownership
| Who | Owns |
|---|---|
| Owner (me) | the *what* and *why*: goals, priorities, every decision, every merge |
| Claude | proposes the *how* (with a recommendation and alternatives), implements, tests, documents, explains |

- Decisions are recorded in `design/decisions.md` (proposed → accepted by the owner).
- **Nothing is merged that the owner doesn't understand.** Unclear code is a reason to ask
  for an explanation or a simplification, not to trust it.
- Claude never merges, never pushes to `main`, and asks before every commit and push.
- The owner regularly writes some code too (small fixes, new fields) and asks Claude to
  review it. This keeps real mastery of the codebase.

## 2. The unit of work: one small PR
Each milestone in `07-roadmap.md` is split into several PRs, each reviewable in about 20–30 minutes.

1. **Plan** (Claude Code *plan mode*): Claude reads the design docs and proposes scope, files,
   approach and tests for this PR. The owner approves or adjusts. No code before approval.
2. **Branch**: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`, created from `main`.
3. **Build**: implementation + tests + doc updates, in small commits.
4. **Self-check**: all local checks green. Optionally an independent review pass
   (`/code-review`) as a second pair of eyes, never instead of the owner's review.
5. **Pull request**, with a description written for the reviewer:
   - **What & why**: the change and the decision(s) it implements (D-xxx);
   - **How to try it**: exact commands / clicks;
   - **Look closely at**: the parts that deserve attention (tricky logic, assumptions);
   - **Alternatives considered** and why they were rejected;
   - **Docs updated**: which design docs changed.
6. **Review**: the owner reads the diff, runs it, and asks questions. Walkthroughs of any
   file are a normal part of review. Fixes are pushed to the same branch.
7. **Merge** (owner only): squash-merge, so each PR becomes one commit on `main`. Delete the branch.

## 3. Git conventions
- `main` is always working and protected: no direct pushes; PRs need green CI.
- Commit messages follow **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`, `ci:`; imperative, ≤ 72 characters in the subject; the body explains *why*.
- **Versioning**: SemVer tags at milestone ends (`v0.1.0` after M1, `v0.2.0` after M2, …;
  `v1.0.0` when the old spreadsheets are fully retired). `CHANGELOG.md` follows *Keep a Changelog*.
- Work tracking: one GitHub milestone per roadmap milestone; one issue per planned PR, linked
  from the PR (`Closes #12`).

## 4. Quality gates
| Gate | Tools | When |
|---|---|---|
| Format + lint | ruff (Python), eslint + prettier (TS) | pre-commit hook and CI |
| Types | mypy `--strict` (Python), `tsc --noEmit` with `strict` (TS) | pre-commit (fast part) and CI |
| Tests | pytest (+ coverage), vitest, Playwright smoke (from M3) | CI on every push / PR |
| Secrets & data | a check that no real data or credentials are staged (`.gitignore` + pre-commit `check-added-large-files`, `detect-private-key`, a custom check rejecting `.xlsx` outside `design/mockups/` and `tests/fixtures/`) | pre-commit and CI |
| Licensing | new dependencies must be GPLv3-compatible; new source files start with `SPDX-License-Identifier: GPL-3.0-or-later` | review |
| Docs | the PR checklist: design docs and `decisions.md` updated if behaviour changed | review |

- **Tests are the specification.** The rules in `00-current-state.md` become tests (parity,
  formula compiler, hand-entry cases). Reviewing tests is the fastest way to check behaviour.
- **Definition of done** for a PR: CI green; tests for new behaviour; docs updated;
  CHANGELOG entry under *Unreleased*; the owner can explain what the change does.
- Dependencies pinned with lock files (`uv.lock`, `pnpm-lock.yaml`); upgrades in their own PRs.

## 5. Data protection (public repo)
The repo is **public**, and training/health notes are personal data (D-034).
- **Never committed**: real journals (`.xlsx` at the repo root, `data/`), backups, local
  snapshots, Google OAuth client secrets and tokens, `.env`, app config. Enforced by
  `.gitignore` and the pre-commit data check.
- **Tests and mock-ups use fictional data only**: generated synthetic workbooks, including
  fixtures in the *legacy* layout for the importer tests, built by a script in the repo.
  Real files are never copied into `tests/`.
- **Program content**: the detailed content of my programs (exercise prescriptions, ladder rungs,
  fear-map scores) lives in my private sheets and is imported locally; the repo ships only
  structure (module YAML) and fictional example reference data. (See Q22 for the summary in
  `00-current-state.md`.)
- Local development runs against **copies** of the real journals (or fictional ones), never the
  live Google Sheets, until a milestone explicitly says otherwise.
- Logs and error messages never print note contents.

## 6. Working sessions with Claude
- **One task per session**: start by reading `CLAUDE.md`, `design/README.md`,
  `07-roadmap.md` and the relevant issue; end with a summary, the roadmap status updated, and
  open questions written into `open-questions.md`.
- **Stay sceptical**: Claude can be confidently wrong. Claims are backed by tests, runs, or
  links to code; "I checked" must say *how* it was checked.
- **Rules live in the repo**: conventions and workflow rules go into `CLAUDE.md` (versioned,
  reviewable), not into Claude's private memory.
- **Learning**: whenever a technology or pattern is new, ask for an explanation with
  examples from this codebase. Understanding the tools is part of owning the project.
- **Permissions**: Claude asks before commits, pushes, installing dependencies, or touching
  anything outside the repo. The owner can tighten or relax this in the Claude Code settings.

## 7. Repository basics (set up in M0)
`README.md` (what it is, screenshots, quick start), `LICENSE` (GPL-3.0-or-later, D-036; already added), `CHANGELOG.md`,
`CONTRIBUTING.md` (short: points to this document), `CLAUDE.md`, `.gitignore`,
`.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/pull_request_template.md`
(the section headings of §2.5), issue templates (feature / bug).
