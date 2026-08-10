# AI Market Report Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an observable, scheduler-agnostic report pipeline that correlates fresh data runs, validates candidate analysis, sends the exact verified report, and preserves daily history.

**Architecture:** GitHub Actions remains the deterministic data and delivery plane. Claude or Codex produces only candidate JSON; GitHub verifies and sends it using files from the current checkout, then archives the run. A request ID ties each cloud dispatch to the correct workflow run.

**Tech Stack:** Python 3.11 standard library + requests, GitHub Actions, Resend HTTP API, unittest.

---

### Task 1: Correlate dispatch with the correct workflow run

**Files:**
- Create: `tests/test_orchestration.py`
- Create: `stock_report/orchestration.py`
- Modify: `.github/workflows/fetch-market-data.yml`
- Modify: `.github/workflows/fetch-market-data-pm.yml`

**Steps:**
1. Write failing tests proving an old completed dispatch is ignored, a matching request ID is selected, and stale snapshots are rejected.
2. Run `python -m unittest tests.test_orchestration -v` and confirm failures are caused by the missing module.
3. Implement the minimal pure selection/freshness functions and CLI wrapper.
4. Add `request_id` workflow inputs and request-aware `run-name` values.
5. Re-run the focused test and the full suite.

### Task 2: Make report generation consume the verified local candidate

**Files:**
- Create: `tests/test_report_input.py`
- Modify: `stock_report.py`
- Modify: `stock_report_pm.py`

**Steps:**
1. Write failing tests for local JSON input taking priority over GitHub API input.
2. Run the tests and confirm the missing local-loader behavior.
3. Add a small shared local JSON loader controlled by explicit file arguments/environment variables.
4. Verify both morning and afternoon paths use the candidate supplied by the workflow.

### Task 3: Verify, send, and archive candidate analysis in one workflow

**Files:**
- Create: `tests/test_pipeline_state.py`
- Create: `stock_report/pipeline_state.py`
- Modify: `.github/workflows/send-report.yml`
- Modify: `.github/workflows/send-report-pm.yml`

**Steps:**
1. Write failing tests for deterministic archive paths and delivery-state construction.
2. Implement path/state helpers.
3. Change workflows to trigger on `*_analysis_candidate.json`, run `verify.py`, render/send using local files, and archive the exact input/output bundle.
4. Preserve manual dispatch for recovery.
5. Validate YAML structure and workflow path filters.

### Task 4: Update cloud playbooks and add a Codex shadow prompt

**Files:**
- Modify: `stock_report/prompts/morning_prompt.md`
- Modify: `stock_report/prompts/afternoon_prompt.md`
- Create: `stock_report/prompts/codex_morning_prompt.md`
- Create: `stock_report/prompts/codex_afternoon_prompt.md`

**Steps:**
1. Replace inline dispatch polling with `orchestration.py` and require its status JSON in analysis.
2. Publish only candidate analysis; let GitHub own verification and delivery.
3. Require previous analysis/ledger review, explicit timestamps, evidence IDs, and bounded probabilistic predictions.
4. Add Codex prompts that implement the same candidate contract through the GitHub connector.

### Task 5: Add health reporting and documentation

**Files:**
- Create: `tests/test_health_check.py`
- Create: `stock_report/health_check.py`
- Create: `.github/workflows/pipeline-health.yml`
- Modify: `README.md`
- Modify: `.github/workflows/README.md`

**Steps:**
1. Write failing tests for missing/stale data and missing delivery detection.
2. Implement deterministic health evaluation with a non-zero exit for unhealthy state.
3. Add scheduled/manual health workflow and Resend alert path.
4. Document the source-of-truth files, recovery flow, Cloudflare handoff, and exact verification commands.

### Task 6: Full verification

**Files:**
- Test: `tests/`

**Steps:**
1. Run `python -m unittest discover -v`.
2. Run Python compile checks with an external bytecode cache.
3. Run `verify.py` against real morning and afternoon fixtures without sending email.
4. Inspect `git diff --check`, `git status`, workflow path filters, and prompt file references.
5. Do not push until the user reviews the diff and explicitly authorizes publication.
