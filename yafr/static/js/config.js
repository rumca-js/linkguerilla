/**
 * YAFR Configuration View Client-Side Script.
 *
 * Handles alpha slider live previews, preset application via AJAX,
 * and reset-to-defaults confirmation.
 */
document.addEventListener("DOMContentLoaded", function () {

  // --- Alpha Slider Live Preview ---
  const visitAlphaSlider = document.getElementById("entries_visit_alpha");
  const visitAlphaBadge = document.getElementById("visit_alpha_badge");
  const visitPreviewText = document.getElementById("visit-preview-text");

  if (visitAlphaSlider) {
    visitAlphaSlider.addEventListener("input", function () {
      const val = parseFloat(this.value).toFixed(2);
      if (visitAlphaBadge) visitAlphaBadge.textContent = val;
      if (visitPreviewText) visitPreviewText.style.opacity = val;
    });
  }

  const deadAlphaSlider = document.getElementById("entries_dead_alpha");
  const deadAlphaBadge = document.getElementById("dead_alpha_badge");
  const deadPreviewText = document.getElementById("dead-preview-text");

  if (deadAlphaSlider) {
    deadAlphaSlider.addEventListener("input", function () {
      const val = parseFloat(this.value).toFixed(2);
      if (deadAlphaBadge) deadAlphaBadge.textContent = val;
      if (deadPreviewText) deadPreviewText.style.opacity = val;
    });
  }

  // --- Quick Preset Buttons (AJAX) ---
  document.querySelectorAll(".btn-apply-preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const preset = this.dataset.preset;
      const originalHtml = this.innerHTML;
      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Applying...';

      $.ajax({
        url: "/api/config/preset",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ preset: preset }),
        success: function (data) {
          if (data.success) {
            showToast("Preset '" + preset + "' applied. Reloading...", "success");
            setTimeout(function () { location.reload(); }, 600);
          } else {
            showToast(data.error || "Failed to apply preset.", "danger");
            btn.disabled = false;
            btn.innerHTML = originalHtml;
          }
        },
        error: function () {
          showToast("Network error while applying preset.", "danger");
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
      });
    });
  });

  // --- Reset to Defaults (AJAX) ---
  const confirmResetBtn = document.getElementById("confirm-reset-btn");
  if (confirmResetBtn) {
    confirmResetBtn.addEventListener("click", function () {
      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Resetting...';

      $.ajax({
        url: "/api/config/reset",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({}),
        success: function (data) {
          if (data.success) {
            showToast("Defaults restored. Reloading...", "success");
            setTimeout(function () { location.reload(); }, 600);
          } else {
            showToast(data.error || "Failed to reset.", "danger");
            confirmResetBtn.disabled = false;
            confirmResetBtn.innerHTML = '<i class="bi bi-arrow-counterclockwise me-1"></i>Confirm Reset';
          }
        },
        error: function () {
          showToast("Network error while resetting.", "danger");
          confirmResetBtn.disabled = false;
          confirmResetBtn.innerHTML = '<i class="bi bi-arrow-counterclockwise me-1"></i>Confirm Reset';
        }
      });
    });
  }

  // --- Toast Helper ---
  function showToast(message, type) {
    const toastEl = document.getElementById("config-toast");
    const toastBody = document.getElementById("config-toast-body");
    if (!toastEl || !toastBody) return;

    toastBody.textContent = message;
    toastEl.className = "toast align-items-center text-white border-0 shadow bg-" + (type || "success");
    const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
    toast.show();
  }

  // --- Remote WebTools Server Connection Test ---
  const testWebtoolsBtn = document.getElementById("btn-test-webtools");
  const webtoolsInput = document.getElementById("remote_webtools_server_location");
  const webtoolsStatus = document.getElementById("webtools-test-status");

  function runWebtoolsTest() {
    if (!webtoolsInput) return;
    const url = webtoolsInput.value.trim();

    if (!url) {
      if (webtoolsStatus) {
        webtoolsStatus.className = "small text-muted";
        webtoolsStatus.innerHTML = '<i class="bi bi-slash-circle me-1"></i>Disabled';
      }
      return;
    }

    if (testWebtoolsBtn) {
      testWebtoolsBtn.disabled = true;
      testWebtoolsBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    }
    if (webtoolsStatus) {
      webtoolsStatus.className = "small text-muted";
      webtoolsStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Testing...';
    }

    $.ajax({
      url: "/api/config/test-webtools",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ url: url }),
      success: function (data) {
        if (testWebtoolsBtn) {
          testWebtoolsBtn.disabled = false;
          testWebtoolsBtn.innerHTML = '<i class="bi bi-activity me-1"></i>Test';
        }
        if (!webtoolsStatus) return;

        if (data && data.online) {
          webtoolsStatus.className = "small text-success";
          webtoolsStatus.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i>Online (' + (data.status_code || 200) + ')';
        } else {
          webtoolsStatus.className = "small text-danger";
          const errDetail = (data && (data.error || data.message)) || "Unreachable";
          webtoolsStatus.innerHTML = '<i class="bi bi-x-circle-fill me-1"></i>' + errDetail;
        }
      },
      error: function () {
        if (testWebtoolsBtn) {
          testWebtoolsBtn.disabled = false;
          testWebtoolsBtn.innerHTML = '<i class="bi bi-activity me-1"></i>Test';
        }
        if (webtoolsStatus) {
          webtoolsStatus.className = "small text-danger";
          webtoolsStatus.innerHTML = '<i class="bi bi-x-circle-fill me-1"></i>Connection error';
        }
      }
    });
  }

  if (testWebtoolsBtn) {
    testWebtoolsBtn.addEventListener("click", runWebtoolsTest);
  }

  if (webtoolsInput && webtoolsInput.value.trim()) {
    runWebtoolsTest();
  }

  // --- Tab Hash Preservation ---
  const currentHash = window.location.hash;
  if (currentHash) {
    const targetTabBtn = document.querySelector('button[data-bs-target="' + currentHash + '"]');
    if (targetTabBtn) {
      const tabInstance = new bootstrap.Tab(targetTabBtn);
      tabInstance.show();
    }
  }

  const tabButtons = document.querySelectorAll('#configTabs button[data-bs-toggle="tab"]');
  tabButtons.forEach(function (btn) {
    btn.addEventListener('shown.bs.tab', function (e) {
      const target = e.target.getAttribute('data-bs-target');
      if (history.replaceState) {
        history.replaceState(null, null, target);
      } else {
        window.location.hash = target;
      }
    });
  });

  // --- Search Views Modal & CRUD Handling ---
  const svModalEl = document.getElementById("searchViewModal");
  const svModal = svModalEl ? new bootstrap.Modal(svModalEl) : null;
  const deleteSvModalEl = document.getElementById("deleteSearchViewModal");
  const deleteSvModal = deleteSvModalEl ? new bootstrap.Modal(deleteSvModalEl) : null;

  function resetSuggestionsContainers() {
    const fContainer = document.getElementById("filter-fields-container");
    const fText = document.getElementById("filter-guide-toggle-text");
    if (fContainer) fContainer.classList.add("d-none");
    if (fText) fText.textContent = "Show Suggestions";

    const oContainer = document.getElementById("order-fields-container");
    const oText = document.getElementById("guide-toggle-text");
    if (oContainer) oContainer.classList.add("d-none");
    if (oText) oText.textContent = "Show Suggestions";
  }

  // 1. Add Search View Button
  const btnAddSv = document.getElementById("btn-add-searchview");
  if (btnAddSv) {
    btnAddSv.addEventListener("click", function () {
      const form = document.getElementById("search-view-form");
      if (form) form.reset();
      document.getElementById("sv_id").value = "";
      document.getElementById("sv-modal-title").textContent = "New Search View";
      document.getElementById("sv_priority").value = "0";
      document.getElementById("sv_default").checked = false;
      resetSuggestionsContainers();
      if (svModal) svModal.show();
    });
  }

  // 2. Edit Search View Button
  document.querySelectorAll(".btn-edit-searchview").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const d = this.dataset;
      document.getElementById("sv_id").value = d.id || "";
      document.getElementById("sv_name").value = d.name || "";
      document.getElementById("sv_priority").value = d.priority || "0";
      document.getElementById("sv_filter_statement").value = d.filterStatement || "";
      document.getElementById("sv_order_by").value = d.orderBy || "";
      document.getElementById("sv_default").checked = (d.default === "1");
      document.getElementById("sv-modal-title").textContent = "Edit Search View: " + (d.name || "");
      resetSuggestionsContainers();
      if (svModal) svModal.show();
    });
  });

  // 3. Save Search View (AJAX with Form Fallback)
  const svForm = document.getElementById("search-view-form");
  if (svForm) {
    svForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const saveBtn = document.getElementById("btn-save-searchview");
      const originalText = saveBtn.innerHTML;
      saveBtn.disabled = true;
      saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Saving...';

      const viewId = document.getElementById("sv_id").value.trim();
      const payload = {
        name: document.getElementById("sv_name").value.trim(),
        default: document.getElementById("sv_default").checked,
        priority: parseInt(document.getElementById("sv_priority").value, 10) || 0,
        filter_statement: document.getElementById("sv_filter_statement").value.trim(),
        order_by: document.getElementById("sv_order_by").value.trim()
      };

      const endpoint = viewId ? ("/api/search-views/" + viewId) : "/api/search-views";

      $.ajax({
        url: endpoint,
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify(payload),
        success: function (data) {
          if (data.success) {
            if (svModal) svModal.hide();
            showToast(data.message || "Search view saved.", "success");
            setTimeout(function () {
              window.location.hash = "#tab-searchviews";
              window.location.reload();
            }, 500);
          } else {
            showToast(data.error || "Failed to save search view.", "danger");
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
          }
        },
        error: function (xhr) {
          let err = "Network error while saving search view.";
          if (xhr.responseJSON && xhr.responseJSON.error) {
            err = xhr.responseJSON.error;
          }
          showToast(err, "danger");
          saveBtn.disabled = false;
          saveBtn.innerHTML = originalText;
        }
      });
    });
  }

  // 4. Set Default Search View (AJAX)
  document.querySelectorAll(".btn-default-searchview").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const viewId = this.dataset.id;
      if (!viewId) return;

      const originalHtml = this.innerHTML;
      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

      $.ajax({
        url: "/api/search-views/" + viewId + "/set-default",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({}),
        success: function (data) {
          if (data.success) {
            showToast(data.message || "Default search view updated.", "success");
            setTimeout(function () {
              window.location.hash = "#tab-searchviews";
              window.location.reload();
            }, 500);
          } else {
            showToast(data.error || "Failed to set default.", "danger");
            btn.disabled = false;
            btn.innerHTML = originalHtml;
          }
        },
        error: function () {
          showToast("Network error while updating default view.", "danger");
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
      });
    });
  });

  // 5. Delete Search View Modal Trigger
  document.querySelectorAll(".btn-delete-searchview").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const viewId = this.dataset.id;
      const viewName = this.dataset.name || "this search view";
      document.getElementById("delete_sv_id").value = viewId;
      document.getElementById("delete-sv-name").textContent = viewName;
      if (deleteSvModal) deleteSvModal.show();
    });
  });

  // 6. Confirm Delete Search View (AJAX)
  const confirmDeleteSvBtn = document.getElementById("confirm-delete-sv-btn");
  if (confirmDeleteSvBtn) {
    confirmDeleteSvBtn.addEventListener("click", function () {
      const viewId = document.getElementById("delete_sv_id").value;
      if (!viewId) return;

      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Deleting...';

      $.ajax({
        url: "/api/search-views/" + viewId,
        method: "DELETE",
        contentType: "application/json",
        data: JSON.stringify({}),
        success: function (data) {
          if (data.success) {
            if (deleteSvModal) deleteSvModal.hide();
            showToast("Search view deleted.", "success");
            setTimeout(function () {
              window.location.hash = "#tab-searchviews";
              window.location.reload();
            }, 500);
          } else {
            showToast(data.error || "Failed to delete search view.", "danger");
            confirmDeleteSvBtn.disabled = false;
            confirmDeleteSvBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Confirm Delete';
          }
        },
        error: function () {
          showToast("Network error while deleting search view.", "danger");
          confirmDeleteSvBtn.disabled = false;
          confirmDeleteSvBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Confirm Delete';
        }
      });
    });
  }

  // 7. Initialize Popovers and Tooltips
  if (typeof bootstrap !== "undefined") {
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.forEach(function (popoverTriggerEl) {
      new bootstrap.Popover(popoverTriggerEl, { sanitize: false });
    });

    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (tooltipTriggerEl) {
      new bootstrap.Tooltip(tooltipTriggerEl);
    });
  }

  // 8. Order By Field Chips Click Handler (appends field to sv_order_by)
  document.querySelectorAll(".order-field-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const field = this.dataset.field;
      const orderInput = document.getElementById("sv_order_by");
      if (!orderInput || !field) return;

      const currentVal = orderInput.value.trim();
      if (!currentVal) {
        orderInput.value = field;
      } else {
        const parts = currentVal.split(",").map(function (s) { return s.trim(); });
        if (!parts.includes(field)) {
          orderInput.value = currentVal + ", " + field;
        }
      }
      orderInput.focus();
    });
  });

  // 9. Toggle Order By Suggestions Container
  const toggleGuideBtn = document.getElementById("toggle-order-fields-guide");
  const guideContainer = document.getElementById("order-fields-container");
  const guideText = document.getElementById("guide-toggle-text");
  if (toggleGuideBtn && guideContainer) {
    toggleGuideBtn.addEventListener("click", function () {
      if (guideContainer.classList.contains("d-none")) {
        guideContainer.classList.remove("d-none");
        if (guideText) guideText.textContent = "Hide Suggestions";
      } else {
        guideContainer.classList.add("d-none");
        if (guideText) guideText.textContent = "Show Suggestions";
      }
    });
  }

  // 10. Filter Statement Field Chips Click Handler (appends token to sv_filter_statement)
  document.querySelectorAll(".filter-field-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const token = this.dataset.filter;
      const filterInput = document.getElementById("sv_filter_statement");
      if (!filterInput || !token) return;

      const currentVal = filterInput.value.trim();
      if (!currentVal) {
        filterInput.value = token;
      } else {
        const parts = currentVal.split(/\s+/);
        if (!parts.includes(token)) {
          filterInput.value = currentVal + " " + token;
        }
      }
      filterInput.focus();
    });
  });

  // 11. Toggle Filter Suggestions Container
  const toggleFilterGuideBtn = document.getElementById("toggle-filter-fields-guide");
  const filterGuideContainer = document.getElementById("filter-fields-container");
  const filterGuideText = document.getElementById("filter-guide-toggle-text");
  if (toggleFilterGuideBtn && filterGuideContainer) {
    toggleFilterGuideBtn.addEventListener("click", function () {
      if (filterGuideContainer.classList.contains("d-none")) {
        filterGuideContainer.classList.remove("d-none");
        if (filterGuideText) filterGuideText.textContent = "Hide Suggestions";
      } else {
        filterGuideContainer.classList.add("d-none");
        if (filterGuideText) filterGuideText.textContent = "Show Suggestions";
      }
    });
  }

});
