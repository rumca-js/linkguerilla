/**
 * rules.js - Entry Rules screen interactions for YAFR.
 *
 * Handles:
 *  - AJAX toggle (enable/disable) for individual rules
 *  - Delete confirmation modal wiring
 */

$(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Toggle Rule Enabled / Disabled                                       */
  /* ------------------------------------------------------------------ */

  $(document).on("click", ".toggle-rule-btn", function () {
    const btn = $(this);
    const ruleId = btn.data("rule-id");

    btn.prop("disabled", true);

    $.ajax({
      url: `/rules/${ruleId}/toggle`,
      method: "POST",
      dataType: "json",
      success: function (data) {
        if (!data.success) {
          showToast("danger", data.error || "Failed to toggle rule.");
          return;
        }

        const enabled = data.enabled;
        const row = $(`#rule-row-${ruleId}`);
        const statusCol = $(`#rule-status-col-${ruleId}`);

        /* Update row opacity */
        row.toggleClass("opacity-50", !enabled);

        /* Update status badge */
        if (enabled) {
          statusCol.html(
            `<span class="badge bg-success-subtle text-success border border-success-subtle">
              <i class="bi bi-check-circle me-1"></i>Enabled
            </span>`
          );
          btn.attr("title", "Disable rule")
             .removeClass("btn-outline-success")
             .addClass("btn-outline-secondary")
             .html('<i class="bi bi-pause-fill"></i>');
        } else {
          statusCol.html(
            `<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">
              <i class="bi bi-pause-circle me-1"></i>Disabled
            </span>`
          );
          btn.attr("title", "Enable rule")
             .removeClass("btn-outline-secondary")
             .addClass("btn-outline-success")
             .html('<i class="bi bi-play-fill"></i>');
        }

        btn.data("enabled", enabled ? "true" : "false");
      },
      error: function () {
        showToast("danger", "Network error — could not toggle rule.");
      },
      complete: function () {
        btn.prop("disabled", false);
      },
    });
  });

  /* ------------------------------------------------------------------ */
  /* Delete Rule — Confirmation Modal                                     */
  /* ------------------------------------------------------------------ */

  let pendingDeleteRuleId = null;

  $(document).on("click", ".delete-rule-btn", function () {
    const btn = $(this);
    pendingDeleteRuleId = btn.data("rule-id");
    const ruleName = btn.data("rule-name") || `Rule #${pendingDeleteRuleId}`;

    $("#delete-rule-modal-text").text(
      `Are you sure you want to permanently delete "${ruleName}"?`
    );
    $("#delete-rule-form").attr("action", `/rules/${pendingDeleteRuleId}/delete`);

    const modal = new bootstrap.Modal(document.getElementById("deleteRuleModal"));
    modal.show();
  });

  /* ------------------------------------------------------------------ */
  /* Test Link Modal & AJAX Evaluation                                    */
  /* ------------------------------------------------------------------ */

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return $("<div>").text(String(str)).html();
  }

  const testModalEl = document.getElementById("testLinkModal");
  if (testModalEl) {
    testModalEl.addEventListener("shown.bs.modal", function () {
      $("#test-url-input").trigger("focus");
    });
  }

  $("#btn-clear-test-url").on("click", function () {
    $("#test-url-input").val("").trigger("focus");
    $("#test-link-empty-state").removeClass("d-none");
    $("#test-link-spinner").addClass("d-none");
    $("#test-link-output").addClass("d-none").empty();
  });

  $("#test-link-form").on("submit", function (e) {
    e.preventDefault();
    const url = $("#test-url-input").val().trim();
    if (!url) {
      showToast("warning", "Please enter a URL to test.");
      $("#test-url-input").trigger("focus");
      return;
    }

    const testBtn = $("#btn-run-test-url");
    const emptyState = $("#test-link-empty-state");
    const spinner = $("#test-link-spinner");
    const output = $("#test-link-output");

    testBtn.prop("disabled", true);
    emptyState.addClass("d-none");
    output.addClass("d-none").empty();
    spinner.removeClass("d-none");

    $.ajax({
      url: "/api/rules/test",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ url: url }),
      dataType: "json",
      success: function (data) {
        if (!data.success) {
          output.html(`
            <div class="alert alert-danger mb-0">
              <i class="bi bi-exclamation-triangle-fill me-2"></i>${escapeHtml(data.error || "Failed to evaluate URL.")}
            </div>
          `).removeClass("d-none");
          return;
        }

        renderTestResults(data);
      },
      error: function (xhr) {
        let msg = "Network error while evaluating URL.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          msg = xhr.responseJSON.error;
        }
        output.html(`
          <div class="alert alert-danger mb-0">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>${escapeHtml(msg)}
          </div>
        `).removeClass("d-none");
      },
      complete: function () {
        spinner.addClass("d-none");
        testBtn.prop("disabled", false);
      },
    });
  });

  function renderTestResults(data) {
    const output = $("#test-link-output");
    output.empty();

    // 1. Verdict Banner
    let verdictHtml = "";
    if (data.is_blocked) {
      let blockReason = "";
      if (data.is_blocked_by_rule && data.is_blocked_by_block_entry) {
        blockReason = "Blocked by matching Entry Rule AND Block Entry pattern.";
      } else if (data.is_blocked_by_rule) {
        blockReason = `Blocked by Entry Rule "${escapeHtml(data.rule_name || "")}".`;
      } else {
        blockReason = "Blocked by Block Entry record.";
      }
      verdictHtml = `
        <div class="alert alert-danger d-flex align-items-center gap-3 py-3 mb-3 shadow-sm border-0">
          <i class="bi bi-slash-circle-fill fs-3 text-danger"></i>
          <div>
            <h6 class="alert-heading mb-1 fw-bold">URL IS BLOCKED</h6>
            <div class="small">${blockReason} Candidate links matching this pattern will be rejected or discarded.</div>
          </div>
        </div>
      `;
    } else {
      verdictHtml = `
        <div class="alert alert-success d-flex align-items-center gap-3 py-3 mb-3 shadow-sm border-0">
          <i class="bi bi-check-circle-fill fs-3 text-success"></i>
          <div>
            <h6 class="alert-heading mb-1 fw-bold">URL IS ALLOWED</h6>
            <div class="small">This link is not blocked and will be accepted for ingestion and processing.</div>
          </div>
        </div>
      `;
    }

    // 2. Canonical Cleaned URL
    const cleanedHtml = `
      <div class="card bg-light border-0 mb-3 px-3 py-2 small">
        <div class="d-flex align-items-center gap-2">
          <span class="text-secondary fw-semibold">Canonical Cleaned URL:</span>
          <code class="text-break flex-grow-1">${escapeHtml(data.cleaned_url)}</code>
        </div>
      </div>
    `;

    // 3. Actions / Effects Summary Badges
    let trustBadge = data.is_trusted
      ? `<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="bi bi-check-circle me-1"></i>Trusted (Status 200)</span>`
      : `<span class="badge bg-light text-muted border px-2 py-1">Untrusted</span>`;

    let tagsBadges = "";
    if (data.auto_tags && data.auto_tags.length > 0) {
      tagsBadges = data.auto_tags
        .map(
          (t) =>
            `<span class="badge bg-info-subtle text-info-emphasis border border-info-subtle me-1"><i class="bi bi-tag me-1"></i>${escapeHtml(t)}</span>`
        )
        .join("");
    } else {
      tagsBadges = `<span class="text-muted small">None</span>`;
    }

    let ageBadge = data.age_limit > 0
      ? `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1"><i class="bi bi-shield-exclamation me-1"></i>Age ${data.age_limit}+</span>`
      : `<span class="text-muted small">None</span>`;

    let actionsHtml = `
      <div class="card border mb-3 shadow-sm">
        <div class="card-header bg-white py-2">
          <span class="fw-semibold small"><i class="bi bi-sliders me-1 text-primary"></i>Applied Rule Actions</span>
        </div>
        <div class="card-body py-2">
          <div class="row g-2 small">
            <div class="col-sm-4">
              <span class="text-secondary d-block">Status Effect:</span>
              ${trustBadge}
            </div>
            <div class="col-sm-4">
              <span class="text-secondary d-block">Age Restriction:</span>
              ${ageBadge}
            </div>
            <div class="col-sm-4">
              <span class="text-secondary d-block">Auto-Attached Tags:</span>
              <div>${tagsBadges}</div>
            </div>
          </div>
        </div>
      </div>
    `;

    // 4. Affecting Entry Rules Table
    let rulesHtml = "";
    if (data.matching_rules && data.matching_rules.length > 0) {
      let rows = data.matching_rules
        .map((r) => {
          let enabledBadge = r.enabled
            ? `<span class="badge bg-success-subtle text-success border border-success-subtle">Enabled</span>`
            : `<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Disabled</span>`;

          let actionBadges = [];
          if (r.block) {
            actionBadges.push(`<span class="badge bg-danger">Block</span>`);
          }
          if (r.trust) {
            actionBadges.push(`<span class="badge bg-success">Trust</span>`);
          }
          if (r.auto_tag) {
            actionBadges.push(`<span class="badge bg-info-subtle text-info-emphasis border">Tag: ${escapeHtml(r.auto_tag)}</span>`);
          }
          if (r.apply_age_limit > 0) {
            actionBadges.push(`<span class="badge bg-warning-subtle text-warning-emphasis border">Age: ${r.apply_age_limit}</span>`);
          }
          if (actionBadges.length === 0) {
            actionBadges.push(`<span class="text-muted">—</span>`);
          }

          return `
            <tr class="${r.enabled ? "" : "opacity-50"}">
              <td class="text-center"><span class="badge bg-secondary-subtle text-secondary border">${r.priority}</span></td>
              <td><strong>${escapeHtml(r.rule_name)}</strong> <small class="text-muted">#${r.id}</small></td>
              <td class="text-center">${enabledBadge}</td>
              <td><code class="small text-break">${escapeHtml(r.matched_pattern || r.trigger_rule_url)}</code></td>
              <td>${actionBadges.join(" ")}</td>
            </tr>
          `;
        })
        .join("");

      rulesHtml = `
        <div class="card border mb-3 shadow-sm">
          <div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
            <span class="fw-semibold small"><i class="bi bi-shield-check me-1 text-primary"></i>Matching Entry Rules (${data.matching_rules.length})</span>
          </div>
          <div class="table-responsive">
            <table class="table table-sm table-hover mb-0 align-middle small">
              <thead class="table-light">
                <tr>
                  <th style="width: 60px;" class="text-center">Priority</th>
                  <th style="width: 170px;">Rule Name</th>
                  <th style="width: 90px;" class="text-center">Status</th>
                  <th>Matched Pattern</th>
                  <th style="width: 180px;">Actions</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      `;
    } else {
      rulesHtml = `
        <div class="alert alert-light border small text-muted mb-3">
          <i class="bi bi-info-circle me-1"></i>No configured Entry Rules matched this URL.
        </div>
      `;
    }

    // 5. Affecting Block Entries Table
    let blocksHtml = "";
    if (data.matching_block_entries && data.matching_block_entries.length > 0) {
      let rows = data.matching_block_entries
        .map((b) => {
          let origin = b.block_list_id
            ? `<span class="badge bg-secondary-subtle text-secondary border">Block List #${b.block_list_id}</span>`
            : `<span class="badge bg-light text-muted border">Manual Entry</span>`;
          return `
            <tr>
              <td><code class="text-break">${escapeHtml(b.url)}</code></td>
              <td class="text-center">${origin}</td>
              <td class="text-center"><span class="badge bg-danger"><i class="bi bi-slash-circle me-1"></i>Blocks URL</span></td>
            </tr>
          `;
        })
        .join("");

      blocksHtml = `
        <div class="card border mb-3 shadow-sm">
          <div class="card-header bg-white py-2 d-flex justify-content-between align-items-center">
            <span class="fw-semibold small text-danger"><i class="bi bi-slash-circle me-1"></i>Matching Block Entries (${data.matching_block_entries.length})</span>
          </div>
          <div class="table-responsive">
            <table class="table table-sm table-hover mb-0 align-middle small">
              <thead class="table-light">
                <tr>
                  <th>Blocked Substring / Pattern</th>
                  <th style="width: 140px;" class="text-center">Origin</th>
                  <th style="width: 120px;" class="text-center">Effect</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      `;
    } else {
      blocksHtml = `
        <div class="alert alert-light border small text-muted mb-0">
          <i class="bi bi-info-circle me-1"></i>No Block Entries (domain or URL block lists) matched this URL.
        </div>
      `;
    }

    output.html(verdictHtml + cleanedHtml + actionsHtml + rulesHtml + blocksHtml).removeClass("d-none");
  }

  /* ------------------------------------------------------------------ */
  /* Auto-dismiss Bootstrap toasts rendered server-side via flash()      */
  /* ------------------------------------------------------------------ */

  $(".toast").each(function () {
    const toast = new bootstrap.Toast(this, { delay: 4000 });
    toast.show();
  });

  /* ------------------------------------------------------------------ */
  /* Helper: show a temporary toast notification                          */
  /* ------------------------------------------------------------------ */

  /**
   * Displays a Bootstrap toast message.
   *
   * @param {string} type  - Bootstrap colour variant ('success', 'danger', etc.)
   * @param {string} text  - Message body text
   */
  function showToast(type, text) {
    const id = `toast-${Date.now()}`;
    const icon = type === "success" ? "check-circle" : "exclamation-triangle";
    const html = `
      <div id="${id}" class="toast align-items-center text-bg-${type} border-0"
           role="alert" aria-live="assertive" aria-atomic="true">
        <div class="d-flex">
          <div class="toast-body">
            <i class="bi bi-${icon} me-2"></i>${text}
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto"
                  data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>`;

    let container = $("#toast-container");
    if (!container.length) {
      container = $(
        '<div id="toast-container" class="position-fixed bottom-0 end-0 p-3" style="z-index:1100;"></div>'
      ).appendTo("body");
    }
    const el = $(html).appendTo(container);
    const toast = new bootstrap.Toast(el[0], { delay: 4000 });
    toast.show();
    el[0].addEventListener("hidden.bs.toast", () => el.remove());
  }
});
