# YAFR File Structure & Directory Layout

This document defines the complete directory tree, file inventory, and module responsibilities for the YAFR application.

---

## 1. Directory Tree Overview

```text
yafr_next/
├── PROJECT.md                                # Project specification & functional requirements
├── ARCHITECTURE.md                           # System architecture, technology choices & subsystems
├── FILES.md                                  # Directory tree & file inventory (this document)
├── URLS.md                                   # Route & endpoint matrix (HTML views & JSON APIs)
├── pyproject.toml                            # Poetry dependencies, build settings & metadata
├── poetry.lock                               # Locked dependency versions
├── Makefile                                  # Command runner (make run, install, test, format, clean)
├── run.py                                    # Application entrypoint & CLI runner (--db, --host, --port)
├── data/                                     # SQLite Database Storage
│   └── table.db                              # Test / development SQLite database containing pre-populated data
│
├── yafr/                                     # Root application package
│   ├── __init__.py                           # App factory & version metadata
│   ├── app.py                                # Flask application initialization & error handlers
│   ├── config.py                             # Configuration loader (defaults & SQLite sync)
│   │
│   ├── db/                                   # Data Access & Repository Layer
│   │   ├── __init__.py                       # Package exports for repositories
│   │   ├── session.py                        # SQLite engine factory, sessionmaker & WAL pragma
│   │   ├── base_repository.py                # BaseRepository with generic CRUD & FIFO limits
│   │   ├── entry_repository.py               # Repository for LinkDataModel & associated tags
│   │   ├── source_repository.py              # Repository for SourcesTable & SourceOperationalData
│   │   ├── job_repository.py                 # Repository for BackgroundJob & History
│   │   ├── history_repository.py             # Repository for SearchHistory & EntryVisitHistory
│   │   ├── rules_repository.py               # Repository for EntryRules & regex rule matching
│   │   ├── search_view_repository.py         # Repository for custom SearchView records
│   │   ├── config_repository.py              # Repository for ConfigurationEntry
│   │   └── logging_repository.py             # Repository for AppLogging with severity levels
│   │
│   ├── search/                               # Query Parsing & SQLite Translation
│   │   ├── __init__.py                       # Search module exports
│   │   ├── parser.py                         # Search expression parser (operators: '=', '==')
│   │   ├── query_builder.py                  # Translates AST into SQLAlchemy expressions
│   │   └── filters.py                        # Predefined search filters (Visited, Read Later, etc.)
│   │
│   ├── services/                             # Business Logic & Domain Services
│   │   ├── __init__.py                       # Service layer exports
│   │   ├── entry_service.py                  # Entry business logic, voting, tags, status updates
│   │   ├── source_service.py                 # Source management, fetch triggering, hash checks
│   │   ├── job_service.py                    # Job creation, pausing, resumption, prioritization
│   │   ├── rule_service.py                   # Rule evaluation engine (regex URLs, auto-tagging)
│   │   ├── preview_service.py                # URL preview metadata & yt-dlp media extraction
│   │   ├── history_service.py                # Search autocomplete, visit tracking & transitions
│   │   ├── search_view_service.py            # SearchView business logic, validation & CRUD
│   │   ├── database_service.py               # DB statistics, table truncating & remote download
│   │   └── logging_service.py                # Application logging helper & log pruning
│   │
│   ├── workers/                              # Asynchronous Background Processing
│   │   ├── __init__.py                       # Worker exports
│   │   ├── worker_manager.py                 # Daemon thread lifecycle controller (start/stop)
│   │   ├── job_executor.py                   # BackgroundJob task dispatcher & execution runner
│   │   ├── source_refresher.py               # SourceRefreshWorker (polling, hashes & interval)
│   │   └── email_reader_adapter.py           # IMAP adapter patching webtoolkit import path
│   │
│   ├── web/                                  # Presentation Layer (Views & Blueprints)
│   │   ├── __init__.py                       # Blueprint registration helper
│   │   ├── context_processors.py             # Global Jinja context (active theme, network state)
│   │   ├── routes_entries.py                 # Views: EntriesListView, DetailView, EditScreen
│   │   ├── routes_sources.py                 # Views: SourcesListView, DetailScreen, EditScreens
│   │   ├── routes_jobs.py                    # Views: JobsView (list, filter, reorder)
│   │   ├── routes_rules.py                   # Views: EntryRulesScreen (regex triggers, auto-tags)
│   │   ├── routes_database.py                # Views: DatabaseView (stats, clear actions, replace)
│   │   ├── routes_status.py                  # Views: StatusView (worker status & network check)
│   │   ├── routes_config.py                  # Views: ConfigurationView (styles, types, alphas)
│   │   ├── routes_credentials.py             # Views: CredentialsScreen (IMAP credentials)
│   │   ├── routes_logs.py                    # Views: LogsView (AppLogging table viewer)
│   │   ├── routes_about.py                   # Views: AboutScreen
│   │   │
│   │   └── api/                              # Lightweight REST / JSON Endpoints
│   │       ├── __init__.py                   # API blueprint export
│   │       ├── api_entries.py                # JSON endpoints: vote, active/dead, bookmark, tags
│   │       ├── api_sources.py                # JSON endpoints: disable, enable, delete, refresh
│   │       ├── api_jobs.py                   # JSON endpoints: pause, resume, cancel, trigger
│   │       ├── api_history.py                # JSON endpoints: autocomplete search, clear visits
│   │       ├── api_status.py                 # JSON endpoints: worker heartbeat, progress info
│   │       ├── api_config.py                 # JSON endpoints: quick theme & display style toggle
│   │       └── api_search_views.py           # JSON endpoints: CRUD & default toggle for SearchViews
│   │
│   ├── templates/                            # Jinja2 HTML Templates
│   │   ├── base.html                         # Base HTML skeleton, theme switcher, modal shells
│   │   │
│   │   ├── components/                       # Reusable Partial Components
│   │   │   ├── navbar.html                   # Navbar with badges for source/job errors
│   │   │   ├── search_widget.html            # Search input, history dropdown, filter selector
│   │   │   ├── entry_item.html               # Polymorphic row (Standard, Gallery, Search, etc.)
│   │   │   ├── source_item.html              # Source row with red dot & error badges
│   │   │   ├── pagination.html               # Page controls / dynamic loading trigger
│   │   │   ├── modal_preview.html            # Video playback / URL preview modal
│   │   │   ├── modal_confirm.html            # Reusable confirmation modal for destructive tasks
│   │   │   └── badge_status.html             # Status indicators (skull, bookmark, unread)
│   │   │
│   │   ├── entries/                          # Entry View Templates
│   │   │   ├── list.html                     # EntriesListView (Google-like centered / top search)
│   │   │   ├── detail.html                   # EntryDetailView (details, voting, transition pane)
│   │   │   └── edit.html                     # EntryEditScreen (metadata form)
│   │   │
│   │   ├── sources/                          # Source View Templates
│   │   │   ├── list.html                     # SourcesListView (pull-to-refresh, progress bar)
│   │   │   ├── detail.html                   # SourceDetailScreen (source metrics & fetch action)
│   │   │   ├── edit_rss.html                 # SourceRssEditScreen
│   │   │   ├── edit_email.html               # SourceEmailEditScreen (IMAP & credentials form)
│   │   │   └── edit_parse.html               # SourceParseEditScreen (XPath parser form)
│   │   │
│   │   ├── credentials/
│   │   │   └── list.html                     # CredentialsScreen
│   │   ├── jobs/
│   │   │   └── list.html                     # JobsView (priority, error count, pause/resume)
│   │   ├── logs/
│   │   │   └── list.html                     # LogsView (log level filter & detail expander)
│   │   ├── rules/
│   │   │   └── list.html                     # EntryRulesScreen (regex URL patterns, auto-tagging)
│   │   ├── database/
│   │   │   └── view.html                     # DatabaseView (table rows, clear caches, replace DB)
│   │   ├── status/
│   │   │   └── view.html                     # StatusView (worker loop & network health)
│   │   ├── configuration/
│   │   │   └── view.html                     # ConfigurationView (display styles, themes, alphas)
│   │   └── about/
│   │       └── view.html                     # AboutScreen
│   │
│   └── static/                               # Static Assets (Offline-Ready)
│       ├── css/
│       │   ├── bootstrap.min.css             # Bootstrap 5 CSS
│       │   ├── bootstrap-icons.css           # Bootstrap Icons CSS
│       │   ├── base.css                      # Core layout styles, transitions & badges
│       │   ├── style-light.css               # DISPLAY_STYLE_LIGHT theme
│       │   ├── style-dark.css                # DISPLAY_STYLE_DARK theme
│       │   ├── display-standard.css          # Feed reader style layout
│       │   ├── display-gallery.css           # YouTube / TikTok thumbnail grid layout
│       │   ├── display-search-engine.css     # Google-like search results layout
│       │   ├── display-content-centric.css   # Reddit-like content preview layout
│       │   └── display-links-only.css        # Compact links-only list
│       ├── js/
│       │   ├── jquery-3.7.1.min.js           # jQuery core library
│       │   ├── bootstrap.bundle.min.js       # Bootstrap 5 bundle (with Popper)
│       │   ├── app.js                        # App-wide utilities: offline toast, notifications
│       │   ├── search.js                     # Search widget, history dropdown, query submission
│       │   ├── entries.js                    # Multi-select, voting, bookmark, visit alpha updates
│       │   ├── sources.js                    # Pull-to-refresh, refresh progress polling
│       │   ├── preview.js                    # URL/Video preview modal lifecycle & player
│       │   └── jobs.js                       # Job pause/resume/delete AJAX interactions
│       └── fonts/
│           ├── bootstrap-icons.woff          # Icon font (woff)
│           └── bootstrap-icons.woff2         # Icon font (woff2)
│
└── tests/                                    # Automated Test Suite (standard library unittest)
    ├── __init__.py
    ├── test_repositories.py                  # Unit tests for Repositories & FIFO limits
    ├── test_search_parser.py                 # Unit tests for search operators (=, ==, LIKE)
    ├── test_services.py                      # Unit tests for business services
    ├── test_workers.py                       # Unit tests for BackgroundJob & SourceRefreshWorker
    └── test_routes.py                        # Integration tests for HTML & JSON API endpoints
```

---

## 2. Detailed File Specifications & Responsibilities

### 2.1 Core Application & Entrypoints

- `data/table.db`
  - **Purpose**: Test and development SQLite database file.
  - **Responsibilities**: Contains pre-populated link entries in `linkdatamodel`, sources in `sourcedatamodel`, configuration in `configurationentry`, tags, search history, and background jobs for local testing.

- `run.py`
  - **Purpose**: Main executable entrypoint for starting the YAFR server.
  - **Responsibilities**: Parses CLI arguments (port, host, `--db` database file path), boots `yafr.app.create_app()`, initiates background workers, and launches the server.
  - **Key Functions**: `main()`, `parse_args()`.

- `yafr/app.py`
  - **Purpose**: Flask application factory and lifecycle coordination.
  - **Responsibilities**: Registers blueprints, registers error handlers (404, 500, DatabaseError), injects global Jinja context, and connects SQLite database session tear-down hooks.
  - **Key Functions**: `create_app(config_object=None)`.

- `yafr/config.py`
  - **Purpose**: Application runtime configuration and identity settings.
  - **Responsibilities**: Defines instance title, description, console/worker terminal window titles, default SQLite path, default themes, pagination limits, and `set_console_title` terminal helper.
  - **Key Classes / Functions**: `Config`, `set_console_title`.

---

### 2.2 Data Access & Repositories (`yafr/db/`)

- `yafr/db/session.py`
  - **Purpose**: SQLite database engine and session factory.
  - **Responsibilities**: Initializes SQLAlchemy engine with `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, and `PRAGMA synchronous=NORMAL`. Exposes scoped sessionmaker.
  - **Key Functions**: `init_db(db_path)`, `get_session()`, `close_session()`.

- `yafr/db/base_repository.py`
  - **Purpose**: Abstract base repository with standard CRUD helpers and storage quota management.
  - **Responsibilities**: Shared session handling, transactional commits, and `apply_storage_limit(model, order_col, max_limit)` for FIFO retention.
  - **Key Classes**: `BaseRepository`.

- `yafr/db/entry_repository.py`
  - **Purpose**: Data access for `LinkDataModel`, `SocialData`, and `EntryCompactedTags`.
  - **Responsibilities**: Query execution for search, single entry retrieval, manual status code updates (200=active, 400=dead), tag updates, cascade deletion of related records (`readlater`, `socialdata`, `entryvisithistory`).
  - **Key Classes**: `EntryRepository`.

- `yafr/db/source_repository.py`
  - **Purpose**: Data access for `SourcesTable` and `SourceOperationalData`.
  - **Responsibilities**: CRUD operations for RSS/Email/Parse sources, operational statistics (`consecutive_errors`, `date_fetched`, `page_hash`, `body_hash`), and cascade deletion of operational data.
  - **Key Classes**: `SourceRepository`.

- `yafr/db/job_repository.py`
  - **Purpose**: Data access for `BackgroundJob` and `BackgroundJobHistory`.
  - **Responsibilities**: Enqueueing tasks, fetching highest priority pending jobs, updating failure counts, toggling enabled state, archiving completed jobs to history.
  - **Key Classes**: `JobRepository`.

- `yafr/db/history_repository.py`
  - **Purpose**: Data access for `SearchHistory`, `EntryVisitHistory`, `EntryTransitionHistory`, and `ReadLater`.
  - **Responsibilities**: Autocomplete query search, recording visits and incrementing counter, logging transitions from one entry to another, toggling Read Later status, and enforcing row limits.
  - **Key Classes**: `HistoryRepository`.

- `yafr/db/rules_repository.py`
  - **Purpose**: Data access for `EntryRules`.
  - **Responsibilities**: Querying active rules ordered by priority, rule creation, updating regex triggers and actions (block, trust, auto-tag).
  - **Key Classes**: `RulesRepository`.

- `yafr/db/config_repository.py`
  - **Purpose**: Data access for `ConfigurationEntry`.
  - **Responsibilities**: Retrieves and updates user preferences (display style, layout type, alphas, storage quotas).
  - **Key Classes**: `ConfigRepository`.

- `yafr/db/logging_repository.py`
  - **Purpose**: Data access for `AppLogging`.
  - **Responsibilities**: Writing application log events (`info_text`, `detail_text`, `level`, `date`), querying logs with level filters, pruning old logs.
  - **Key Classes**: `LoggingRepository`.

---

### 2.3 Search Engine & Query Translation (`yafr/search/`)

- `yafr/search/parser.py`
  - **Purpose**: Parses raw user input strings into structured search tokens and operators.
  - **Responsibilities**: Tokenizes key-value expressions (`=`, `==`), field directives (`title=`, `description=`, `tag=`), free-text tokens, and sorting directives (`order:published`).
  - **Key Classes/Functions**: `SearchParser`, `ParsedQuery`, `SearchClause`.

- `yafr/search/query_builder.py`
  - **Purpose**: Translates `ParsedQuery` AST into SQLAlchemy filter expressions.
  - **Responsibilities**: Emits indexed `LIKE` clauses for `=`, exact equality for `==`, full-text composite clauses for free-text, and joins for tags/social data.
  - **Key Classes**: `SearchQueryBuilder`.

- `yafr/search/filters.py`
  - **Purpose**: Encapsulates predefined system search filters.
  - **Responsibilities**: Provides filter statements for "Visited", "Read Later", "by Date published", "by Votes", and "by Visits".
  - **Key Classes**: `FilterRegistry`, `SearchFilter`.

---

### 2.4 Domain & Business Services (`yafr/services/`)

- `yafr/services/entry_service.py`
  - **Purpose**: Coordinates entry workflows.
  - **Responsibilities**: Search execution, detail loading, voting logic (-100 to 100), manual status changes, tag updates, and comments management.
  - **Key Classes**: `EntryService`.

- `yafr/services/source_service.py`
  - **Purpose**: Source lifecycle and refresh coordination.
  - **Responsibilities**: Validating URLs, adding RSS/Email/Parse sources, triggering refresh tasks, computing operational diffs, and formatting badge states.
  - **Key Classes**: `SourceService`.

- `yafr/services/job_service.py`
  - **Purpose**: Task lifecycle and job management.
  - **Responsibilities**: Enqueueing standard jobs (`JOB_PROCESS_SOURCE`, `JOB_LINK_UPDATE_DATA`), pausing/resuming jobs, batch deletion.
  - **Key Classes**: `JobService`.

- `yafr/services/rule_service.py`
  - **Purpose**: Entry rules processing engine.
  - **Responsibilities**: Compares incoming or existing URLs against regex patterns (`trigger_rule_url`), evaluates block/trust status, and assigns auto-tags.
  - **Key Classes**: `RuleService`.

- `yafr/services/preview_service.py`
  - **Purpose**: URL inspection and rich media preview extractor.
  - **Responsibilities**: Checks rule blocking status, extracts YouTube/media information via `yt-dlp`, fetches OpenGraph titles and descriptions.
  - **Key Classes**: `PreviewService`.

- `yafr/services/history_service.py`
  - **Purpose**: Search suggestions and browsing navigation recorder.
  - **Responsibilities**: Provides autocomplete suggestions from `SearchHistory`, records visits, logs entry transitions, and manages Read Later list.
  - **Key Classes**: `HistoryService`.

- `yafr/services/database_service.py`
  - **Purpose**: Database administrative tasks.
  - **Responsibilities**: Calculates table row counts, triggers cache truncations (search history, visits, social data), and safely replaces SQLite file from URL.
  - **Key Classes**: `DatabaseService`.

---

### 2.5 Background Workers (`yafr/workers/`)

- `yafr/workers/worker_manager.py`
  - **Purpose**: Lifecycle manager for background daemon threads.
  - **Responsibilities**: Starts, stops, and reports health of `WorkerDaemon`. Ensures graceful shutdown upon SIGINT/SIGTERM.
  - **Key Classes**: `WorkerManager`.

- `yafr/workers/job_executor.py`
  - **Purpose**: Background task dispatcher.
  - **Responsibilities**: Pulls enabled jobs from `backgroundjob`, dispatches to matching handlers, captures exceptions, and updates retry counts.
  - **Key Classes**: `JobExecutor`.

- `yafr/workers/source_refresher.py`
  - **Purpose**: Continuous source updater (`SourceRefreshWorker`).
  - **Responsibilities**: Checks outdated sources (>1 hour old), compares page and body hashes, parses feeds, adds new entries, and increments error counters.
  - **Key Classes**: `SourceRefreshWorker`.

- `yafr/workers/email_reader_adapter.py`
  - **Purpose**: Adapter for email source fetching.
  - **Responsibilities**: Bridges IMAP connections and fixes `webtoolkit.utils.emailreader` import bug before invoking feed extraction.
  - **Key Classes**: `EmailReaderAdapter`.

---

### 2.6 Presentation & Controllers (`yafr/web/`)

- `yafr/web/context_processors.py`
  - **Purpose**: Injects application-wide variables into Jinja2 templates.
  - **Responsibilities**: Supplies active display theme (`style-light`/`style-dark`), layout type, error badge counters for sources and jobs, and offline status.

- `yafr/web/routes_entries.py`
  - **Purpose**: View controller for entry browsing.
  - **Responsibilities**: Renders `EntriesListView` (empty centered search or top bar), `EntryDetailView`, and `EntryEditScreen`.

- `yafr/web/routes_sources.py`
  - **Purpose**: View controller for sources.
  - **Responsibilities**: Renders `SourcesListView`, `SourceDetailScreen`, `SourceRssEditScreen`, `SourceEmailEditScreen`, and `SourceParseEditScreen`.

- `yafr/web/routes_jobs.py`
  - **Purpose**: View controller for jobs management (`JobsView`).

- `yafr/web/routes_rules.py`
  - **Purpose**: View controller for entry rules (`EntryRulesScreen`).

- `yafr/web/routes_database.py`
  - **Purpose**: View controller for database management (`DatabaseView`).

- `yafr/web/routes_status.py`
  - **Purpose**: View controller for background worker and system status (`StatusView`).

- `yafr/web/routes_config.py`
  - **Purpose**: View controller for application configuration (`ConfigurationView`).

- `yafr/web/routes_credentials.py`
  - **Purpose**: View controller for credentials overview (`CredentialsScreen`).

- `yafr/web/routes_logs.py`
  - **Purpose**: View controller for log viewing (`LogsView`).

- `yafr/web/routes_about.py`
  - **Purpose**: View controller for application about information (`AboutScreen`).

- `yafr/web/api/*.py`
  - **Purpose**: Lightweight REST / JSON API endpoints.
  - **Responsibilities**: Small server functions returning JSON payloads for dynamic client-side interactions (voting, bookmarking, source toggling, batch deletions).

---

### 2.7 Frontend Assets & Templates (`yafr/static/` & `yafr/templates/`)

- `templates/components/entry_item.html`: Polymorphic card template switching layout based on `display_type` (Standard, Gallery, Search Engine, Content Centric, Links Only).
- `templates/components/search_widget.html`: Reusable search input with autocomplete dropdown, search button, and filter selector.
- `static/js/search.js`: Client-side query handler, debounced autocomplete, and filter persistence.
- `static/js/entries.js`: Dynamic interactions for voting, read-later toggle, dead alpha updates, and multi-select batch actions.
- `static/js/sources.js`: Pull-to-refresh implementation and live polling of source update progress.
- `static/css/*.css`: Theme styling (`style-light.css`, `style-dark.css`) and card layouts.
