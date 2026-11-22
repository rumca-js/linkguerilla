# Ticket: [004] Implement ImportView HTML Route, UI Template, and Client Script

- **Status**: open
- **Dependencies**: [003_import_api_endpoints.md]
- **Spec Reference**: @markdown/SPEC.md#Section-1, @markdown/SPEC.md#Section-2, @markdown/SPEC.md#Section-4

## Description
Build the user-facing Import view (`ImportView`) accessible via `/import`, add the navigation link to the top navbar, provide responsive Bootstrap 5 form controls for selecting host paths, choosing target data models, configuring duplicate policies, and integrating AJAX path validation and background job submission.

## Implementation Details
- Files to create/modify:
  - `yafr/web/routes_import.py`:
    - Define Blueprint `import_bp` with route `GET /import` rendering `import/view.html`.
  - `yafr/web/__init__.py`:
    - Register `import_bp` with Flask application.
  - `yafr/templates/import/view.html`:
    - Bootstrap 5 layout with breadcrumbs and title card.
    - Path input field with live validation feedback badge and "Check Path" button.
    - Target Model selector dropdown (`Auto-detect`, `Links (linkdatamodel)`, `Sources (sourcedatamodel)`).
    - Conflict Resolution indicator (`Skip existing duplicates`).
    - Enqueue button with loading state.
    - Success/Alert container displaying created Job ID with direct link to `/jobs`.
  - `yafr/templates/components/navbar.html`:
    - Add "Import" item with `<i class="bi bi-box-arrow-in-down me-1"></i>Import` pointing to `import_view.import_view` with active route indicator.
  - `yafr/static/js/import.js`:
    - Asynchronous validation call on blur or button click to `/api/import/validate-path`.
    - Form submission handler posting to `/api/import/enqueue`.
    - Dynamic alert rendering and form reset.

## Acceptance Criteria
- [ ] Navigating to `/import` renders `ImportView` with HTTP 200.
- [ ] Navbar displays active "Import" link.
- [ ] Form enables entering server path, validating it, selecting target model, and enqueueing job.
- [ ] Client script handles errors gracefully and links to `/jobs` on success.
- [ ] Integration tests added in `tests/test_routes_import.py` verifying template rendering and context variables.
- [ ] All tests passing cleanly.
- [ ] No regressions in existing test suite.
