# Feature Specification: Data Import UI and Background Job Processing

## 1. Problem Statement & Scope
- Problem: YAFR users currently have no web interface to bulk import link entries or feed/email sources from existing local archives or datasets on the host machine. Importing requires manual CLI invocation or manual link-by-link entry creation.
- In Scope:
  - ImportView UI at `/import` with navigation link in the top navigation bar.
  - Server-side host filesystem path input for selecting files or directories.
  - Target model selection: Auto-detect (default), Links (`linkdatamodel`), or Sources (`sourcedatamodel`).
  - Extensible import architecture starting with JSON file/directory parsing, designed to easily incorporate OPML and plain text link lists.
  - Conflict resolution policy: Skip existing records (prevent duplicate URLs or overwriting existing curated metadata).
  - Background task enqueueing via `POST /api/import/enqueue` creating a `JOB_IMPORT_FROM_FILES = "import-from-files"` job in SQLite `backgroundjob`.
  - Background worker handler (`ImportJobHandler`) executing the import job asynchronously, updating job progress/results, recording in `backgroundjobhistory`, and logging issues to `applogging`.
  - Frontend async job status feedback and direct link to `/jobs` view.
- Out of Scope:
  - Browser allows only to upload small files (showed, when import directory is empty, allows to select files from import if not
  - OPML and plain link list parsers (deferred to follow-up tickets; architecture must support them via pluggable handlers).
  - Export functionality not handled by this user story

## 2. User Stories & Acceptance Criteria
- US-1: As an archivist or administrator, I want to navigate to an Import screen from the navbar so that I can configure and initiate bulk imports of saved links and sources.
  - [ ] A dedicated "Import" link is visible in the top navbar and highlights when `/import` is active.
  - [ ] The Import screen renders a form with host filesystem path input, target model selector (Auto-detect, Links, Sources), conflict policy (Skip existing), and a submission button.
  - [ ] The Import form displays clear guidance on supported file formats (JSON) and path syntax.

- US-2: As an administrator, I want the system to validate the server-side filesystem path before submitting so that I do not enqueue jobs for non-existent or unreadable paths.
  - [ ] If the path does not exist on the host, the UI shows a descriptive error message without enqueueing a job.
  - [ ] If the path exists but contains no matching files, an error or warning is returned.
  - [ ] If the path is valid, the request enqueues a background job and displays a confirmation banner with the job ID and a link to the Jobs view.

- US-3: As a user, I want large file or directory imports to run in the background so that the web interface remains fast and responsive.
  - [ ] Triggering an import creates a BackgroundJob record with job="import-from-files" in the SQLite database.
  - [ ] The background worker picks up the job and processes all files within the directory or target file without blocking web requests.
  - [ ] Progress and error counts are maintained; upon completion, the job is archived to `backgroundjobhistory` with total imported and skipped record counts.
  - [ ] If existing entries or sources with identical URLs are encountered, they are skipped without failing the entire batch.

## 3. Data & Schema Changes
- No schema alterations or database migrations required. Existing tables are leveraged:
  - `backgroundjob`: stores pending and running jobs (job="import-from-files", subject=path, args=json serialized options).
  - `backgroundjobhistory`: records completed/failed job outcome, execution time, and summary statistics.
  - `linkdatamodel`: receives imported link entries.
  - `sourcedatamodel`: receives imported feed/email sources.
  - `applogging`: captures error and warning notifications.

## 4. API & Endpoint Contracts
- HTML View Route:
  - GET /import: Renders ImportView (`yafr/templates/import/view.html`). Returns HTTP 200 with page context and active navigation state.
- JSON API Endpoints:
  - POST /api/import/validate-path:
    - Request Body: JSON `{"path": "/absolute/path/to/data"}`
    - Success (200 OK): `{"ok": true, "path": "/absolute/path/to/data", "is_dir": true, "file_count": 5, "detected_type": "json"}`
    - Error (400 Bad Request): `{"ok": false, "error": "Path does not exist on host filesystem"}`
  - POST /api/import/enqueue:
    - Request Body: JSON `{"path": "/absolute/path/to/data", "target": "auto" or "links" or "sources", "conflict_strategy": "skip"}`
    - Success (200 OK): `{"ok": true, "job_id": 42, "job_type": "import-from-files", "message": "Import job enqueued successfully"}`
    - Error (400 Bad Request): `{"ok": false, "error": "Invalid target model or path"}`
    - Error (500 Server Error): `{"ok": false, "error": "Database error while creating job"}`

## 5. Architecture & Flow
- Sequence:
  1. User navigates to `/import` in the web browser.
  2. User selects file from existing file from import folder (e.g. `./import/links.json` or `./import/link_dir`) and chooses target model. User can also select file to upload
  3. Client-side JS (`import.js`) posts to `POST /api/import/enqueue`.
  4. API route validates the path on the host filesystem and creates a `BackgroundJob` row via `JobService.create_job()`.
  5. API responds with HTTP 200 and the created `job_id`.
  6. The background worker loop (`JobExecutor`) polls `backgroundjob` ordered by priority.
  7. `JobRegistry` routes `import-from-files` to `ImportJobHandler`.
  8. `ImportJobHandler` loads the appropriate importer strategy (`JsonLinkImporter` or `JsonSourceImporter`).
  9. Importer parses each file, checks for existing URLs in the database, inserts missing entries, and increments statistics (imported, skipped, failed).
  10. Worker moves the job to `backgroundjobhistory` with full summary details and logs any parsing anomalies in `applogging`.

## 6. Edge Cases & Failure Modes
- Path Does Not Exist: Caught at validation and API level before enqueuing. If path is removed before worker execution, worker records an error in `backgroundjob.errors`, logs to `applogging`, and fails the job cleanly.
- Corrupted or Malformed JSON: Importer logs warning per malformed file/record and continues processing remaining valid entries rather than aborting the entire directory import.
- Duplicate URL Collisions: Detected via query on normalized URL; existing entries are skipped to preserve existing ratings, tags, and metadata.
- Large Directories (Thousands of Files): Importer processes files sequentially in chunks, committing transactions in batches (e.g. 100 entries per commit) to maintain low memory usage and avoid SQLite locking timeouts.
- Symlinks and Recursive Directories: Importer ignores recursive directory symlinks to avoid infinite filesystem loops.

## 7. Security & Observability
- Path Traversal & Restricted Paths: Validation ensures only readable files/directories are processed. Restricted system directories (e.g. `/proc`, `/sys`, `/dev`) can be blocked.
- Observability:
  - Jobs appear immediately in `/jobs` list with pending state and priority.
  - Real-time error badges in navbar increment if job encounters unrecoverable errors.
  - Informative log entries created in `applogging` table with severity `NOTIFICATION` on completion and `WARNING`/`ERROR` on malformed inputs.
  - Full execution outcome recorded in `backgroundjobhistory` with duration, total records processed, skipped, and inserted.
