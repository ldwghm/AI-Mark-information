# Codex Scheduled Connector Trigger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let Codex Web Scheduled trigger fresh GitHub-hosted market data and publish shadow candidates using only the GitHub connector.

**Architecture:** Codex updates a mode-specific trigger JSON on `main`; a path-filtered push workflow fetches data and stamps the exact request metadata into latest JSON. Codex polls for the matching request ID, analyzes the snapshot, and writes to a non-delivery shadow path until the user explicitly cuts over.

**Tech Stack:** Python 3.11 standard library, GitHub Actions, GitHub Connector, unittest, Markdown prompts.

---

### Task 1: Define and stamp the connector request contract

**Files:**
- Create: `tests/test_connector_trigger.py`
- Create: `stock_report/connector_trigger.py`
- Create: `stock_report/triggers/morning.json`
- Create: `stock_report/triggers/afternoon.json`

**Steps:**
1. Write failing tests for exact request stamping, missing request IDs, and wrong-mode triggers.
2. Run `python -m unittest tests.test_connector_trigger -v` and confirm the module is missing.
3. Implement minimal trigger validation, snapshot stamping, and a CLI that updates one JSON file.
4. Re-run the focused test and confirm all cases pass.

### Task 2: Trigger fetch workflows from connector file updates

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `.github/workflows/fetch-market-data.yml`
- Modify: `.github/workflows/fetch-market-data-pm.yml`

**Steps:**
1. Add failing workflow contract tests for the mode-specific push path and stamping command.
2. Run `python -m unittest tests.test_workflows -v` and confirm the new assertions fail.
3. Add push path filters and a push-only stamping step after each fetch script.
4. Add trigger and latest paths to the existing commit step without changing schedule or workflow_dispatch behavior.
5. Re-run workflow tests and parse all workflow YAML files.

### Task 3: Replace token-based Codex shadow prompts

**Files:**
- Modify: `tests/test_prompts.py`
- Modify: `stock_report/prompts/codex_morning_prompt.md`
- Modify: `stock_report/prompts/codex_afternoon_prompt.md`
- Create: `stock_report/data/shadow/morning_analysis_candidate.json`
- Create: `stock_report/data/shadow/afternoon_analysis_candidate.json`

**Steps:**
1. Add failing prompt tests requiring connector trigger/poll/update steps and forbidding PAT, shell dispatch, and production candidate paths.
2. Run `python -m unittest tests.test_prompts -v` and confirm the existing shadow prompts fail the contract.
3. Write self-contained connector-native prompts for morning and afternoon shadow tasks.
4. Re-run prompt tests and verify shadow paths do not match delivery workflow filters.

### Task 4: Document setup, cutover, and verification

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/README.md`
- Create: `docs/codex-scheduled-setup.md`

**Steps:**
1. Document GitHub connection requirements, Web Scheduled creation, shadow monitoring, and the single-scheduler cutover rule.
2. Document trigger recovery and request-ID inspection.
3. Run the full unittest suite with `TEMP` and `TMP` set to a writable task directory.
4. Run Python compile checks, YAML parsing, `git diff --check`, and a secret-pattern scan.
5. Inspect the complete diff, commit the scoped files, push the feature branch, and integrate only after verification.
