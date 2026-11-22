# Ticket: [003] Implement Path Validation & Job Enqueue REST API Endpoints

- **Status**: open
- **Dependencies**: [001_core_import_service.md]
- **Spec Reference**: @markdown/SPEC.md#Section-4

## Description
Provide lightweight RESTful API endpoints under `/api/import` allowing the frontend to validate candidate host filesystem paths before job creation and to enqueue an asynchronous import task into the `backgroundjob` table.

## Implementation Details
- Files to create/modify:
  - `yafr/web/api/api_import.py`:
    - `POST /api/import/validate-path`:
      - Accepts JSON payload: `{"path": str}`.
      - Checks path existence, readability, whether directory or single file, and counts compatible `.json` files.
      - Returns `{"ok": true, "path": str, "is_dir": bool, "file_count": int, "detected_type": str}` or `{"ok": false, "error": str}` (HTTP 400).
    - `POST /api/import/enqueue`:
      - Accepts JSON payload: `{"path": str, "target": str, "conflict_strategy": str}`.
      - Validates path and arguments.
      - Calls `JobService.create_job(job=JOB_IMPORT_FROM_FILES, subject=path, args=json_payload, priority=50)`.
      - Returns `{"ok": true, "job_id": int, "job_type": "import-from-files", "message": str}` (HTTP 200).
  - `yafr/web/api/__init__.py`:
    - Register import API routes in the API blueprint.

## Acceptance Criteria
- [ ] `POST /api/import/validate-path` validates real host paths and returns proper JSON metadata or 400 errors.
- [ ] `POST /api/import/enqueue` inserts a `BackgroundJob` record in SQLite with proper `job`, `subject`, and `args`.
- [ ] Invalid request payloads or non-existent paths return HTTP 400 with descriptive error messages.
- [ ] Unit/integration tests added in `tests/test_import_api.py`.
- [ ] All tests passing cleanly.
- [ ] No regressions in existing test suite.
