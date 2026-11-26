# Feature Specification: WebToolsWrapper SocialData Integration

## 1. Problem Statement & Scope
- Problem: webtoolkit dependency was updated (v0.1.88+) such that RemoteUrl and BaseUrl social inspection methods (get_social_data and get_social_properties) return a SocialData dataclass instance instead of a Python dictionary. WebToolsWrapper currently enforces isinstance(props, dict), causing get_social_properties() to return an empty dictionary. Consequently, background social data downloads (JOB_LINK_DOWNLOAD_SOCIAL) and URL preview requests fail to extract and persist engagement metrics.
- In Scope:
  - Implement WebToolsWrapper.get_social_data() returning Optional[webtoolkit.SocialData].
  - Update WebToolsWrapper.get_social_properties() to return a dictionary via props.to_dict() when receiving a SocialData instance, while preserving raw dictionary passthrough for legacy handlers and mocks.
  - Update LinkDownloadSocialJobHandler in yafr/workers/jobs/link_jobs.py to query get_social_data(), persist populated metrics when len(social_data) > 0 into the socialdata table, and log warnings when social_data.errors is populated.
  - Verify PreviewService maintains seamless JSON serialization with dictionary output from get_social_properties().
  - Update and expand unit test suites in tests/test_webtools_wrapper.py and tests/test_workers.py to cover SocialData objects, dictionary fallbacks, metric persistence, and error handling.
- Out of Scope:
  - Database schema migrations or alterations to SQLite tables (socialdata table remains as defined in linkarchivetools).
  - Modifying webtoolkit internal implementation or classes.
  - Linking webtoolkit as a local path dependency in pyproject.toml (standard package dependency is maintained).

## 2. User Stories & Acceptance Criteria
- US-1: As a background worker executing JOB_LINK_DOWNLOAD_SOCIAL, I want WebToolsWrapper to provide parsed social metrics from webtoolkit SocialData instances so that entry engagement statistics (views, ratings, thumbs, stars, followers) are persisted to the database.
  - [ ] WebToolsWrapper.get_social_data() returns an Optional[SocialData] instance when querying RemoteUrl or BaseUrl handlers.
  - [ ] LinkDownloadSocialJobHandler extracts metrics from SocialData and updates the corresponding record in the socialdata table.
  - [ ] If len(social_data) == 0 (no metrics populated), the database record is not mutated unnecessarily.
  - [ ] If social_data.errors is non-empty, warnings are logged to application logs without failing the background job.

- US-2: As a downstream consumer such as PreviewService or existing UI routes, I want WebToolsWrapper.get_social_properties() to continue returning a standard Python dictionary so that JSON responses and templates operate without regressions.
  - [ ] WebToolsWrapper.get_social_properties() returns props.to_dict() when the underlying handler returns a SocialData instance.
  - [ ] If the underlying handler returns a dict directly, get_social_properties() passes it through unmodified.
  - [ ] On handler exceptions or unhandled returns, an empty dict {} is returned safely.

- US-3: As a developer maintaining the codebase, I want test suites to validate both SocialData objects and legacy dictionary fallbacks so that changes to webtoolkit or mocking conventions do not break social data handling.
  - [ ] Unit tests verify WebToolsWrapper.get_social_data() handling with SocialData instances.
  - [ ] Unit tests verify WebToolsWrapper.get_social_data() auto-conversion from dictionary using SocialData.from_dict().
  - [ ] Unit tests verify WebToolsWrapper.get_social_properties() returning dict representations of SocialData.
  - [ ] Unit tests verify LinkDownloadSocialJobHandler persistence logic and error logging when receiving SocialData.

## 3. Data & Schema Changes
- Database schema changes: None.
- Existing tables and models are preserved:
  - socialdata table in SQLite via linkarchivetools.model.definitions.SocialData.
  - Columns: id, entry_id, thumbs_up, thumbs_down, view_count, rating, upvote_ratio, upvote_diff, upvote_view_ratio, stars, followers_count, date_updated.
- Model mapping:
  - webtoolkit.SocialData dataclass metrics are cast via _to_int and _to_float before being assigned to linkarchivetools.model.definitions.SocialData attributes.
  - sources and errors lists on webtoolkit.SocialData remain in-memory and are logged to application logs; they are not stored in database columns.

## 4. API & Endpoint Contracts
- External HTTP endpoints:
  - No new routes or schema changes to existing REST endpoints.
  - POST /api/preview/metadata continues returning JSON containing social dictionary:
    - Status: 200 OK
    - Payload property social: object containing social metric keys and values.
  - POST /api/entries/<id>/update-social continues enqueueing JOB_LINK_DOWNLOAD_SOCIAL.
- Internal service contracts:
  - WebToolsWrapper.get_social_data() -> Optional[webtoolkit.SocialData]:
    - Queries url_handler.get_social_data() or url_handler.get_social_properties().
    - Returns webtoolkit.SocialData or None.
  - WebToolsWrapper.get_social_properties() -> Dict[str, Any]:
    - Returns dictionary representation of social metrics, or empty dict {}.

## 5. Architecture & Flow
- Flow for background social data ingestion:
  - 1. Link creation or refresh enqueues JOB_LINK_DOWNLOAD_SOCIAL for entry_id.
  - 2. Background worker executes LinkDownloadSocialJobHandler.
  - 3. Handler initializes WebToolsWrapper for entry URL.
  - 4. WebToolsWrapper instantiates RemoteUrl or BaseUrl handler.
  - 5. Handler calls web_client.get_social_data().
  - 6. WebToolsWrapper retrieves SocialData from handler.
  - 7. If social_data.errors exists, handler logs a warning message.
  - 8. If len(social_data) > 0, handler retrieves or creates socialdata record, updates metric values, sets date_updated, and commits transaction.
  - 9. Background job completes successfully.
- Flow for page preview:
  - 1. User submits URL to preview endpoint.
  - 2. PreviewService calls WebToolsWrapper.get_social_properties().
  - 3. WebToolsWrapper converts SocialData to dict using props.to_dict().
  - 4. PreviewService returns JSON response with serialized social data.

## 6. Edge Cases & Failure Modes
- Handler returns None or raises exception: WebToolsWrapper catches errors, logs debug message, and returns None for get_social_data() and {} for get_social_properties().
- Handler returns legacy dict: WebToolsWrapper.get_social_data() safely converts dict to SocialData via SocialData.from_dict(props); get_social_properties() returns the dict as-is.
- Partial source failures: webtoolkit.SocialData can populate available metrics while appending failures to social_data.errors. The job persists valid metrics and logs error warnings without marking the job as failed.
- Metric count is zero: When len(social_data) == 0, database records are not updated, avoiding empty timestamp updates.
- Idempotency: Multiple job executions update the existing socialdata row for entry_id without creating duplicate entries.

## 7. Security & Observability
- Observability:
  - Warnings logged via logger.warning when social_data.errors contains reported issues.
  - Debug logs emitted for handler invocation failures without exposing credentials or internal tokens.
  - Background job execution recorded in backgroundjobhistory table.
- Security:
  - All database interactions use parameterized SQLAlchemy ORM operations.
  - Network timeouts (15s default) prevent hanging worker threads during remote social data retrieval.
