# Ticket: [001] Implement Extensible Data Import Service & JSON Parsers

- **Status**: open
- **Dependencies**: None
- **Spec Reference**: @markdown/SPEC.md#Section-3, @markdown/SPEC.md#Section-5

## Description
Implement the core data import service and extensible importer strategy architecture. Provides `ImportService` and modular importers (`JsonLinkImporter`, `JsonSourceImporter`) to parse JSON data files and directories from the host filesystem, validate schema compatibility, map records to `linkdatamodel` and `sourcedatamodel`, and insert records using a duplicate-skip strategy without blocking transactions.

## Implementation Details
- Files to create/modify:
  - `yafr/services/import_service.py`:
    - Define abstract `BaseImporter` strategy interface.
    - Implement `JsonLinkImporter` for parsing JSON arrays/objects into `LinkDataModel` rows.
    - Implement `JsonSourceImporter` for parsing JSON arrays/objects into `SourcesTable` rows.
    - Implement `ImportService.import_path(path, target="auto", conflict_strategy="skip", session=None)`:
      - Validates filesystem path existence and readability.
      - Discovers matching data files (single file or recursive directory scan).
      - Auto-detects target model by inspecting JSON keys (e.g. `url`/`title` vs `feed_url`/`type`) when `target="auto"`.
      - Skips existing entries with duplicate URLs to protect curated data.
      - Executes batch database commits (e.g. 100 entries per batch) for memory efficiency.
      - Returns summary dict: `{"imported": int, "skipped": int, "failed": int, "files_processed": int, "errors": list}`.

## Acceptance Criteria
- [ ] Code implemented according to conventions in `yafr/services/import_service.py`.
- [ ] Unit tests added in `tests/test_import_service.py` covering:
  - Single JSON file import for links into `LinkDataModel`.
  - Single JSON file import for sources into `SourcesTable`.
  - Directory scan and multi-file JSON import.
  - Auto-detection logic for links vs sources.
  - Duplicate skipping policy (existing records remain unchanged).
  - Malformed JSON handling (errors logged, valid files continue).
- [ ] All tests passing cleanly.
- [ ] No regressions in existing test suite.
