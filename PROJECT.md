# PROJECT

 - The primary function of the application is searching.
 - The application searches local SQLite database
 - Search results contain links to web pages.
 - The application does not require an internet connection to search local databases.
 - Internet access is required when fetching databases, sources, or web pages.
 - This instruction should contain brief statements.
 - Do not run unit tests before making changes. You can run them after changes have been done
 - Though database supports Users table, we use only one user

A database is a searchable collection of entries.
 - Active database file: `data/table.db` (used for local testing and development).
 - It is a HTML self-hosted app
 - do not run tests before starting work on a feature. Run it after feature is implemented

This project provides Makefile that provides rules to start app, and start worker.
Provide docker script?
I have many instances of app in mind. Running app on a different port should be relatively easy.
It should listen to connections from LAN

 - App can be started with 'make run'
 - Tests can be started with 'make test'

# Files
Files describing project:
 - ARCHITECTURE.md
 - FILES.md
 - URLS.md
 - BUGS.md - if any bug is define should be solved
 - TODO.md - identified what is left to do

# Data
 - webtoolkit for network communication https://github.com/rumca-js/webtoolkit

# SQLite data model

 - The SQLite data model is defined by linkarchivetools.
 - The authoritative model definition is: https://github.com/rumca-js/linkarchivetools/blob/main/linkarchivetools/model/definitions.py

Naming vs Table names
 - Entries - linkdatamodel
 - Sources - sourcedatamodel
 - Configuration - configurationentry
 - Visited Entries History - entryvisithistory
 - Entry Transitions History - entrytransitionhistory
 - SearchHistory - search history
 - Read Later - readlater
 - Credentials - credentials (used for email source type)
 - AppLogging - applogging (logs). Follows logging levels
 - SearchView, or Filters - searchview
 - Block Entry Lists - blockentrylist
 - Block Entries - blockentry

linkdatamodel table dependencies:
 - linkdatamodel.id = entrycompactedtags.entry_id
 - linkdatamodel.id = socialdata.entry_id
 - linkdatamodel.source_id = sources.id
 - linkdatamodel.id = readlater.entry_id
 - linkdatamodel.id = entryvisithistory.entry_id

source table dependencies:
 - sourcedatamodel.id = sourceoperationaldata.source_id

linkarchivetools business classes (controllers) vs tables. You may propose changes to these classes
 - Entries - linkarchivetools
 - EntryTags - tags logic
 - Sources - sourcedatamodel
 - SourceData - sourceoperationaldata
 - AppLogging - applogging
 - SearchView - searchview
 - CheckLater - readlater
 - BackgroundJob - backgroundjob
 - ConfigurationEntry - configurationentry

# UI
 - validate input links.
 - link should not contain white spaces at start/end. Trim them on input
 - Propose clickable suggestions that replaces input
 - webtoolkit.UrlLocation().get_clean() returns cleaned version of link (proposition to the user)
 - link should not have trailing / character (propose version without it)
 - propose link version without www if it has in it (e.g. https://www.example.com -> https://example.com)
 - propose HTTPS link version if http is used
 - if it is not web link webtoolkit.UrlLocation().is_web_link() display error
 - if ConfigurationEntry does not allow specific type of of link display error, but allow such links to be inserte by
  the user
 - the system should not add link that is not accepted by ConfigurationEntry.accept* fields (accept_domain_link, accept_non_domain_links, etc)
 - should apply for entry inserts or source inserts
 - each view should provide title. Entry detail should display title, source detail should display title. Lists should display list title, with search words (if there are any)
 - preferably views should have one place with autofocus. Search views on search input

 - Any input should be limited. Do not allow infinite amount of inputs. For example entries can be inserted by a textfield, but only allow 200 to ba added by one field at a time
 - Link addition UI provides a quick modal from navbar and EntriesListView with live validation, clickable proposition buttons, and a batch ingestion tab for up to 200 URLs.

# JobsView
 - displays list of jobs
 - allows to create a job
 - user can select jobs to remove, or pause, or resume
 - user can clear all jobs or clear all erroneous jobs
 - duplicate jobs with identical properties (job, subject, task, args) are not added to the queue
 - user should be able to select order of jobs (by enabled, date_created, errors)
 - user should be able to filter by type (infos, errors, warnings, etc)

# Browsing
 - Every entry visit is recorded (if configured so).
 - Visit information is stored in the UserEntryVisitHistory SQLite table (`entryvisithistory`).
 - The application can display the user's visited entries.
 - The application can clear the user's visit history.
 - Entries can be saved to read later, stored in the `readlater` SQLite table.
 - The application can display and clear the user's read later entries.
 - When EntryDetailScreen is visited, it contains pane below to which entries user transitions to.
 - Entry transitions are maintained by UserEntryTransitionHistory SQLite table (`entrytransitionhistory`).

## Sources refresh
 - disabled sources should be skipped
 - sources that were fetched earlier than hour since source.date\_fetch should be skipped
 - should use order of sources by last fetched (or that never have been fetched)
 - should change date\_fetch, but only after attempt to read source has been made
 - if database is change, the worker should not process any older data for previous database
 - source.SourceOperationalDataRepository has page_hash (entire source hash), and body_hash (body, or entries hash). If it is not different than previous one, you can skip refresh, and mark as read
 - SourceOperationalDataRepository stores the amount of source entries, consecutive_errors contain the amount of consecutive errors. Is cleared when valid response is received.
 - source is marked as read when it's response is valid, if it is not consecutive errors counter is incremented
 - all links from sources (or from jobs) should pass through some EntryLinkBuilder
 - each entry inherits some properties of source (if source property is defined). language, age. if source.auto_tag is defined it should also add said tags

## Entry creation
 - it shall check ConfigurationEntry if link of this type is accepted or not. ConfigurationEntry has fields to accept_domain_links, etc. It should also check entry rules, if are blocking entries
 - when inserting check if link already exist (exact check)
 - when inserting check if https:// exists, or non-www, and try to add it
 - what about github where users or repositories can have different casing?

# Jobs
 - Background task / worker script processes jobs sequentially from `backgroundjob` ordered by priority.
 - when checking if links, or sources are outdated - put only one job into the queue. We will mitigate starvation that way
 - Identifies job types based on `linkarchivetools.BackgroundJob`:
   - `JOB_PROCESS_SOURCE = "process-source"`: Fetches feeds/sources, checks content hashes, parses entries, and persists new links.
   - `JOB_LINK_UPDATE_DATA = "link-update-data"`: Refreshes properties from `BaseUrl`/`RemoteUrl` via `WebToolsWrapper`: title, description, thumbnail, date_published, author, album, language, HTTP status_code. Only updates properties when valid. Updates `date_update_last` to 'now'. If link is not valid, sets `date_dead_since`; if valid, clears it. If link is blocked by entry rules, it is removed. Automatically enqueues `JOB_LINK_DOWNLOAD_SOCIAL`.
   - `JOB_LINK_DOWNLOAD_SOCIAL = "link-download-social"`: Downloads social metadata (`url.get_social_properties`) and updates ratings and visit counters.
   - `JOB_CLEANUP = "cleanup"`: Enforces storage quotas and retention limits.
 - Direct WebToolkit Metadata Extraction: `webtoolkit` (`BaseUrl` or `RemoteUrl`) was introduced to provide parsing and reading of titles, descriptions, date_published, author, etc. Do not fall back on response, nor use beautiful soup. Either BaseUrl/RemoteUrl works, or not.
 - When there are no jobs in the queue, the worker decides what should be done next:
   - Checks how many sources to fetch (outdated sources exceeding refresh period), adds `process-source` jobs into the queue, and processes them.
   - Checks how many entries to update: `ConfigurationEntry.number_of_update_entries` is used to identify how many update jobs can be added if no job is in queue. Candidate entries are selected ordered by oldest `date_update_last` (`nullsfirst`), and up to `number_of_update_entries` `link-update-data` jobs are enqueued and processed.
   - The update process updates `date_update_last` to 'now'.
 - Job processing is executed as a background worker runner (`JobExecutor` / worker loop).

# Databases management
It should be possible to download a new database .db file from the internet, or elsewhere.

# Code Requirements
 - prefer having small server functions that returns JSON data.
    -- for example /api/source-disable/123 should disable source 123, and provide JSON response
 - provide interactive UI, that fetches data when necessary
 - use bootstrap 5, you can use javascript, jQuery
 - create a javascript libraries that handles code that could be reused between views (escapeHtml, etc)
 - pages should be quite responsive. Not all page contents need to be refreshed when action is performed, some sections can be fetched as needed
 - prefer using css files for styles
 - when removing rows remember to remove rows that depend on it. For example some tables depend on linkdatamodel entries
 - Use small functions.
 - Keep classes small and focused.
 - Divide functionality into small files.
 - Give each class a clear responsibility.
 - Avoid duplicating database access logic.
 - Keep UI code separate from database and networking code.
 - Use repositories for database access.
 - Use appropriate abstractions for downloading files and fetching web pages.
 - Provide API documentation using Doxygen-style comments.
 - Document public classes.
 - Document public methods.
 - Document non-obvious implementation decisions.
 - Use descriptive names for classes, methods, and variables.
 - Prefer simple implementations over unnecessary abstractions.
 - Prefer simiplicity of calls and structure
 - When handling SQLite tables, then apply some storage limits. For example, we may store history of user searches. Do not allow for infinite growth, but allow only a fixed amount of entries to be added. New entries replace old ones. One exception is Entries. There is no limit for them
 - when creating views check if url can be accessed. Even if we don't have yet any 'permissions' we will be able to addd it later
 - consider batch operations to obtain data. There can be many rows in link database.

# General Requirements
 - The application must remain usable when the device is offline.
 - use reasonable directory structure. UI elements, or components should have their directories, controller logic should be separated, model, etc.
 - Network operations must not block the UI thread.
 - Network failures must be handled gracefully.
 - Use webtoolkit.BaseUrl or webtoolkit.RemoteUrl to read links, RSS sources, parse sources. webtoolkit was introduced to provide parsing and reading of titles, descriptions, date_published, author, etc. Do not fall back on response, nor to use beautiful soup. Either BaseUrl/RemoteUrl works, or not.
 - Database failures must be reported to the user (eg. SQLite errors).
 - Long-running operations must expose their current state.
 - Destructive operations must require user confirmation.
 - The application must preserve locally available databases when network operations fail.
 - The application must not modify a local database unless the user explicitly requests an update or refresh.
 - If a modification control cannot be hidden, it must be disabled.
 - if network is disabled network related widgets, like buttons should be not visible

# Views
 - EntriesListView - default 'search' google like view
 - EntryDetailView - view showing only one result (entry), similar to YouTube video preview
 - EntryEditScreen - Adds or edits an entry.
 - SourcesListView - view showing sources (RSS channels, etc.)
 - SourceListView - shows one source information
 - SourceRssEditScreen - Edits source
 - SourceEmailEditScreen - Edits source
 - SourceParseEditScreen - Edits source
 - CredentialsScreen - displays credentials information
 - JobsView - view showing jobs
 - LogsView - view showing AppLogging entries. There should be a limit to number of logs. Maybe up to 2000?
 - EntryRulesScreen - Displays and configures entry rules.
 - BlockEntriesScreen - Displays and manages individual BlockEntry records with pagination and search (keeps EntryRulesScreen responsive with large block lists).
 - BlockListsScreen - Displays and manages BlockEntryList plain text block lists.
 - AboutScreen - Shows information about the application.
 - UrlPreview - shows preview for link. Link can be passed to it from other places of software
    - it should say if link is blocked, and if it is by which rule
 - DatabaseView - shows database information
 - StatusView - shows status of app, if background task reading jobs is working
 - ConfigurationView - allows user to change configurationentry properties (display style)
 - ExportView - provides ability to export data. Can export sources into OPML, pure link list, entries from linkdatamodel into lists of ilnks
 - ImportView - provides ability to import data from files: JSON into linkdatamodel, or into sourcedatamodel, OMPL into sourcedatamodel
 - provide ability to add/edit search views

# Status, Indications, and Badges
 - The status API endpoint (`/api/status`) returns JSON describing operational health and UI indications (`indications`) and quantitative badges (`badges`).
 - Configuration settings are not status flags; if a configuration setting affects whether a UI portion is displayed, the indication provides a `visible` boolean:
   - `indications.worker`: contains `visible` boolean (based on `configurationentry.enable_background_jobs`). When `visible` is true, indicates `active` and `message`. When `visible` is false, UI worker badge is hidden and worker health flags are omitted.
   - `indications.webtools`: contains `visible` (configured) and `ok` (server online).
   - `indications.database`: contains `ok`.
   - `indications.sources`: contains `ok` (`sources_errors == 0`).
   - `indications.jobs`: contains `ok` (`jobs_errors == 0`).
 - Badges (`badges`) provide quantitative counts for pills:
   - `badges.sources_outdated`: count of outdated sources.
   - `badges.sources_errors`: count of sources with error status.
   - `badges.jobs_errors`: count of failed background jobs.
 - There might be additional /api/status endpoints/routes that provide additional data if required.

# ConfigurationView
 - DISPLAY_STYLE_LIGHT = "style-light"
 - DISPLAY_STYLE_DARK = "style-dark"

 - DISPLAY_TYPE_STANDARD = "standard"
 - DISPLAY_TYPE_GALLERY = "gallery"
 - DISPLAY_TYPE_SEARCH_ENGINE = "search-engine"
 - DISPLAY_TYPE_CONTENT_CENTRIC = "content-centric"
 - DISPLAY_TYPE_LINKS_ONLY = "links-only"

 - CONFIGURATION_SEARCH_ENGINE = "Search Engine"
 - CONFIGURATION_GALLERY = "Gallery"
 - CONFIGURATION_NEWS = "News"

 click_behavior_modal_window is used to load a modal windoww for preview (for youtube etc.)

 - Configuration view should contain presets for type of initialization
 - should provide means to configure and view credentials

## EntriesListView
 - if user did not input anything the input text should be quite big, and in the middle. If user enters anything the search should be above
 - Provides search widget with text input
 - search history is stored in SearchHistory table, when user inputs search, this table data is used to help user select previous texts
 - Search widget has a clock-history button that opens a dropdown of all recent searches from SearchHistory (unfiltered). Clicking an item fills the search input and submits the search
 - As the user types in the search input, autocomplete suggestions are shown filtered by the current text (debounced, prefix match from SearchHistory)
 - Provides buttons: to add new entry, to mark all entries as read
 - Search widget has "Search" button and a button
 - provide "filters" selection to allow search only 'read later' entries
 Filters are read from SQLite table, but if it nos available by default by Date published filter should be used. Always some filter need to be applied
   -- "Visited" filter - entry results should visited entries
   -- "Read Later" filter - entry results should entries marked for read later
   -- "by Date published" - shows entries, but with this order applied (date_published)
   -- "by Votes" - shows entries, but with this order applied (page_rating_votes)
   -- "by Visits" - shows entries, but with this order applied (page_rating_visits)
 - Search supports advanced search capabilities (described later)
 - Search results support page navigation (or dynamic loading of next / prev elements)
 - Selecting an entry opens EntryDetailScreen.
 - should support selection of multiple entries, and perform actions on them (delete)
 - can support lazy loading (but does not have to) if we had many embedded youtube previews, etc
 - user should be able to change display style, or type from this place, or change if clicking on entry should lead into entry.link, or local preview, or if icons should be shown
 - user should be able to use batch operations on selected links: delete / bookmark / unbookmark / copy

### EntryListItem - row in EntryListScreen
There are several list styles:
 - Gallery (emphasis on thumbnail, should look like YouTube or TikTok). If entry.thumbnail is not set, or empty, and source.favicon is not, then favicon should be displayed as small icon, just as for Standard display
 - Standard (similar to gallery, but thumbnail is smaller, and on the left, should remind Feed readers
 - Search engine (emphasis on title, and showing actual link. Should look like search engine results)
 - Conent centric - reddit-like. Shows more of description. Allows user to interact with entry, like set its properties.

 Entry Item shall display:
 - entry.thumbnail or source.favicon
 - title (for safety we can display up to characters?)
 - date of publish
 - source.title
 - social data if it is defined for entry (views, followers_count, thumbs etc), and if configuration.enable\_social\_data is true
 - tags if it is defined for entry, in format #tag. These should be clickable, should lead into EntryListView with this tag
 - bookmark icon if bookmarked
 - skull indicator if dead
 - language if it is not empty, or not ""
 - should indicate via badge if entry.age is > 0 (age limited)

 If thumbnail is not available, then it should be skipped.
 - Visited entries apply configurable visit alpha.
 - Dead entries apply configurable dead alpha.
 - Bookmarked entries, or entries with votes do not apply alpha (remain fully opaque).

## Search
 - Search is performed against the selected database.
 - Pressing search without any textual input should work, then all entries should be returned using specified order
 - there should be help somewhere which instructs user about the available syntax
 - Implement search input translation layer. Search should also support following operators:
    -- "=" acts like LIKE Sql operator. E.g. title=youtube shall find all entries with youtube in title
    -- "==" expects right argument to match. E.g. title==youtube shall find all entries with title exactly as youtube
 - Search expressions are translated to the underlying database format.
    -- SQLite databases use SQLite search capabilities.
    -- JSON databases provide equivalent search behavior where possible.
 - Search can match the entry title.
 - Search can match the entry description.
 - Search can support expressions such as:
 - title LIKE '%something%'
 - description LIKE '%something%'
 - Search implementation should use appropriate SQLite indexes where possible.
 - The search implementation should support large databases efficiently.
 - provide ability to support order (at least) by
    -- page rating votes
    -- date created
    -- date published
    -- followers count
    -- stars
    -- page rating visits
 - search syntax might have effect on SearchViews (filter statement, or order by)

## EntryDetailScreen
Displays the details of an entry.

Provides the following actions:
 - Check later (adds or removes entry from Read Later).
 - Vote
 - Edit.
 - Set language
 - Url Preview.
 - Remove.
 - mark active (sets manual_status_code to 200)
 - mark dead (sets manual_status_code to 400)
 - update link data
 - reset link data
 - change publication date
 - copy link to clipboard

The screen displays, where available:
 - Thumbnail, or video playback frame (if thumbnail is available, if icons are enabled in configuration)
 - Title.
 - Link.
 - Date of publish
 - Tags, followed with pen icon to edit tags
 - Source information
 - Buttons for some operations like: "Check status", "Add vote"
   -- vote allows user to input digit between -100 and 100. The value can be defined from the user. It should not be 'increased or decreased. It is just defined by the user
 - Description. User should be able to select text in it. Should make https:// links a real links
 - Button to add a comment (with comments). Comments can be edited.
 - Other entry metadata.
 - Entry transition pane. The pane shows entries that the user previously visited from the current entry. Entry transitions are stored in UserEntryTransitionHistory.
 - back button returning to EntryListScreen should not refresh list, nor should scroll to the top, as it does not modify Entries, or results. It should if read later were changed and EntryList is with read later filter, or if EntryList is with sort by Visits
 - provide links leading to other places: web archive, schema validation, who is etc.
 - social data (number of views, followers), but only if social data for entry exists, and configuration.enable_social_data is true

## EntryEditScreen
 - Allows adding a new entry or editing an existing entry.
 - Provides input fields for entry metadata (URL, title, description, tags, author, etc.).
 - Does not allow to check link directly. There should be a lock icon, that needs to be pressed to change it

## SourcesListScreen
 - small search box at top with results list displayed by default (no big search box)
 - Provides buttons
    - add - prompts user to select source type (SOURCE_TYPE_RSS or SOURCE_TYPE_EMAIL)
    - fetch - visible when any sources is outdated or has consecutive errors and can be refreshed. Prompts user if sources with errors should be refetched
 - Selecting source opens SourceDetailScreen.
 - Provides search widget, similar to EntryListScreen
 - Similarly to EntryListScreen should contain "Search" button with a button to apply filter (order by title, or fetch time)
 - Filters should be by Url, Title, Fetch time, number of errors. By default by Url filter should be applied. A filter always need to be applied
 - Probably it would have to be a different search widget implementation from EntryListScreen. These can share same base class though
 - Source fetch means that body of page is fetched, should be RSS, entries are read from it, and inserted into linkdatamodel table.
 - If possible fetch/refresh button should spin if sources are being refreshed
 - Supports pull to refresh to reload sources from the active database
 - Displays a linear progress indicator showing sources update/refresh progress when SourceRefreshWorker is running
 - search widget should, just as EntryListScreen support LIKE syntax
 - should support selection of multiple entries, and perform actions on them (delete, refresh)

### SourceListItem - row in SourcesListScreen
 - Displays source thumbnail or favicon
 - Displays source title and URL
 - Displays a red dot badge on the item (top right) when the source requires refresh (outdated fetch)
 - Displays an error badge when consecutive errors occurred on fetch
 - Disabled sources apply configurable dead alpha

## SourceDetailScreen
 - Displays information about a source.
 - Provides following actions:
    -- Fetch / Update
    -- Edit.
    -- Remove.
 - The Fetch action downloads the source content from the internet.
     button should not be active, if it is fetch job (process-source) in jobs
 - The source content is expected to be RSS or a compatible feed.
 - Entries are extracted from the source content.
 - Extracted entries are inserted into the linkdatamodel table.
 - Existing entries should not be duplicated.

## SourceEditScreen
 - Allows adding a new RSS source or editing an existing source.
 - Provides input fields for source title, URL, and enabled status via shared SourceFormPane component.
 - Does not allow to check url directly. There should be a lock icon, that needs to be pressed to change it

## SourceEmailEditScreen
 - Allows adding a new Email source or editing an existing Email source.
 - Provides input fields for IMAP server URL, username, and password.
 - Automatically persists credentials into the credentials table and sets Source.credentials_id.
 - Saves changes to the sourcedatamodel table in the active database.
 - Only accessible when the active database is writable.
 - Email sources are supported by webtoolkit/webtoolkit/utils/emailreader. Is something is missing there indicate
 - Email sources entries are inserted into database as links, where link is in format email://{source.id}/{message.id}
 - emails are read only for 24 last hours

## DatabaseScreen
- displays database information
- Provides the following actions:
  -- Edit - edits display name of the database
- Displays the database name.
- Displays the database type.
- Displays the local file information.
- Displays the remote URL, if applicable.
- Displays the date of creation.
- Displays the date of last refresh/update.
- Displays the number of rows in relevant tables.
- Provides an action to clear the search history.
- Provides an action to clear the user's visited entries.
- Provides an action to clear the user's read later entries.
- Provides an action to clear the social data.
- Provides an action to clear the sources data.
- Provides an action to clear the links data (and cascades to dependent records).
- implement pull to refresh data about database
- user should be able to replace database with database from URL. It shall download and replace the database file. Should user restart process then?

## EntryRulesScreen
 - you can use fields: trigger_rule_url, rule_name, enabled, priority, block, trust, auto_tag, apply_age_limit, source_id. Other fields do not have to be used right now
 - trigger_rule_url supports re syntax ".*reddit.com.*" should work
 - multiple rules can be defined in a single rule, eg. ".*reddit.com.*, .*github.com.*"
 - Block entries are not displayed directly as a monolithic table in EntryRulesScreen to ensure fast rendering when handling thousands of entries. Instead, a "Blocked Urls" button with a badge count navigates to BlockEntriesScreen with search and pagination controls.

## BlockEntriesScreen
 - Displays BlockEntry items (blocked URLs, domains, and patterns) with server-side pagination and search.
 - Supports fast lookup, page controls (previous, next, page numbers), per-entry deletion, and adding new blocked URLs via modal or dedicated form.

## SearchView

 - support only name, default, priority
    filter_statement  (same as format as user search statement),
    order_by (ascending and descending should be supported. Proposing format like in django link sorts ascending -link sorts descending. should support multiple order_by columns, delimited with , character
    fields for now
 - currently it can be only used for searching linkdatamodel
