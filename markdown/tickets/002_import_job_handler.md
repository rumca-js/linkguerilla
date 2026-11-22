# Ticket: [002] Implement ImportJobHandler for Background Worker

- **Status**: open
- **Dependencies**: [001_core_import_service.md]
- **Spec Reference**: @markdown/SPEC.md#Section-5, @markdown/SPEC.md#Section-6, @markdown/SPEC.md#Section-7

## Description
Integrate the background job processor with data import operations by implementing `ImportJobHandler` for job type `JOB_IMPORT_FROM_FILES = "import-from-files"`. The handler delegates parsing and persistence to `ImportService`, tracks imported/skipped counts, writes audit logs to `applogging`, and archives execution outcomes to `backgroundjobhistory`.

## Implementation Details
- Files to create/modify:
  - `yafr/workers/jobs/import_jobs.py`:
    - Define `ImportJobHandler(BaseJobHandler)` handling `JOB_IMPORT_FROM_FILES`.
    - Extract target path from `job.subject`.
    - Extract configuration parameters (`target`, `conflict_strategy`) from `job.args` JSON.
    - Invoke `ImportService.import_path()`.
    - Emit `applogging` records (`NOTIFICATION` level with summary counts upon success; `WARNING`/`ERROR` upon failure).
    - Return execution result payload with `consume=True` and statistics.
  - `yafr/workers/jobs/registry.py`:
    - Register `ImportJobHandler()` in `create_default_registry()`.
  - `yafr/workers/jobs/__init__.py`:
    - Export `ImportJobHandler` and `JOB_IMPORT_FROM_FILES`.

## Acceptance Criteria
- [ ] `ImportJobHandler` handles `JOB_IMPORT_FROM_FILES = "import-from-files"`.
- [ ] Handler correctly parses JSON options from `job.args` and target path from `job.subject`.
- [ ] Handler records summary log in `applogging` and returns `consume=True` with imported/skipped counts.
- [ ] If path is missing or invalid, handler logs error, handles retry count, or consumes job on fatal error.
- [ ] `ImportJobHandler` registered in `JobRegistry`.
- [ ] Unit tests added in `tests/test_import_worker.py`.
- [ ] All tests passing cleanly.
- [ ] No regressions in existing test suite.
