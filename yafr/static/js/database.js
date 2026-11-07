/**
 * YAFR Database View Client-Side Script
 *
 * Handles pulling live database statistics, editing the display title,
 * executing cache truncations, and downloading remote database archives.
 */
document.addEventListener("DOMContentLoaded", function () {
  var activeClearEndpoint = null;
  var activeClearTable = null;
  var activeClearExtraTables = null;

  // 1. Refresh Database Statistics (Pull to refresh)
  $("#refresh-stats-btn").on("click", function () {
    var btn = $(this);
    var icon = $("#refresh-stats-icon");

    btn.prop("disabled", true);
    icon.addClass("spinner-border spinner-border-sm text-secondary me-1").removeClass("bi bi-arrow-clockwise");

    $.ajax({
      url: "/api/database/stats",
      type: "GET",
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          // Update Overview Fields
          $("#display-db-name").text(resp.database_name);
          $("#display-file-size").text(resp.file_size_formatted);
          $("#display-file-bytes").text(
            (resp.file_size_bytes || 0).toLocaleString() + " bytes"
          );
          $("#display-date-refresh").text(resp.date_last_refresh || "—");
          $("#display-date-created").text(resp.date_created || "—");
          $("#display-db-file").text(resp.database_file || "—");

          // Update Table Counts
          if (resp.tables) {
            $.each(resp.tables, function (tableName, count) {
              var formatted = (count || 0).toLocaleString();
              $("#table-count-" + tableName).text(formatted);
              $("#badge-count-" + tableName).text(formatted + " rows");
            });
          }
        } else {
          alert("Failed to refresh database stats: " + (resp.error || "Unknown error"));
        }
      },
      error: function () {
        alert("Network error refreshing database statistics.");
      },
      complete: function () {
        btn.prop("disabled", false);
        icon.removeClass("spinner-border spinner-border-sm text-secondary").addClass("bi bi-arrow-clockwise");
      },
    });
  });

  // 2. Edit Database Display Name
  $("#edit-db-name-form").on("submit", function (e) {
    e.preventDefault();
    var submitBtn = $("#save-db-name-btn");
    var newName = $("#db-name-input").val().trim();

    if (!newName) {
      alert("Database display name cannot be empty.");
      return;
    }

    submitBtn.prop("disabled", true).html(
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Saving...'
    );

    $.ajax({
      url: "/api/database/update-name",
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify({ instance_title: newName }),
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          $("#display-db-name").text(resp.instance_title);
          var modalEl = document.getElementById("editDbNameModal");
          var modal = bootstrap.Modal.getInstance(modalEl);
          if (modal) modal.hide();
        } else {
          alert("Failed to update name: " + (resp.error || "Unknown error"));
        }
      },
      error: function () {
        alert("Network error updating database name.");
      },
      complete: function () {
        submitBtn
          .prop("disabled", false)
          .html('<i class="bi bi-check-lg me-1"></i>Save Name');
      },
    });
  });

  // 3. Clear Table Button Click (opens confirmation modal)
  $(document).on("click", ".clear-table-btn", function () {
    var btn = $(this);
    activeClearEndpoint = btn.data("endpoint");
    activeClearTable = btn.data("table");
    activeClearExtraTables = btn.data("extra-tables") || null;
    var label = btn.data("label") || activeClearTable;

    $("#confirm-clear-title").text("Clear " + label);
    $("#confirm-clear-message").html(
      "Are you sure you want to permanently clear all records from <strong>" +
        label +
        "</strong>?"
    );

    var modal = new bootstrap.Modal(document.getElementById("confirmClearModal"));
    modal.show();
  });

  // 4. Confirm Execute Clear Action
  $("#execute-clear-btn").on("click", function () {
    if (!activeClearEndpoint) return;

    var btn = $(this);
    btn.prop("disabled", true).html(
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Clearing...'
    );

    $.ajax({
      url: activeClearEndpoint,
      type: "POST",
      dataType: "json",
      success: function (resp) {
        var modalEl = document.getElementById("confirmClearModal");
        var modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();

        if (resp.success) {
          if (activeClearTable) {
            $("#table-count-" + activeClearTable).text("0");
            $("#badge-count-" + activeClearTable).text("0 rows");
          }
          if (resp.deleted_counts) {
            $.each(resp.deleted_counts, function (tbl) {
              $("#table-count-" + tbl).text("0");
              $("#badge-count-" + tbl).text("0 rows");
            });
          }
          if (activeClearExtraTables) {
            var extras = activeClearExtraTables.split(",");
            for (var i = 0; i < extras.length; i++) {
              var t = extras[i].trim();
              if (t) {
                $("#table-count-" + t).text("0");
                $("#badge-count-" + t).text("0 rows");
              }
            }
          }
        } else {
          alert("Failed to clear data: " + (resp.error || "Unknown error"));
        }
      },
      error: function () {
        alert("Network error clearing database records.");
      },
      complete: function () {
        btn
          .prop("disabled", false)
          .html('<i class="bi bi-trash me-1"></i>Clear Data');
        activeClearEndpoint = null;
        activeClearTable = null;
        activeClearExtraTables = null;
      },
    });
  });

  // 5. Replace Database from URL Form Submission
  $("#replace-db-form").on("submit", function (e) {
    e.preventDefault();
    var submitBtn = $("#confirm-replace-db-btn");
    var remoteUrl = $("#remote-db-url-input").val().trim();

    if (!remoteUrl) {
      alert("Remote database URL is required.");
      return;
    }

    if (!remoteUrl.startsWith("http://") && !remoteUrl.startsWith("https://")) {
      alert("URL must start with http:// or https://");
      return;
    }

    submitBtn.prop("disabled", true).html(
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Downloading & Swapping...'
    );

    $.ajax({
      url: "/api/database/replace-from-url",
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify({ remote_url: remoteUrl }),
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          alert(resp.message || "Database replaced successfully.");
          window.location.reload();
        } else {
          submitBtn
            .prop("disabled", false)
            .html('<i class="bi bi-cloud-arrow-down me-1"></i>Download & Replace');
          alert("Database replacement failed: " + (resp.error || "Unknown error"));
        }
      },
      error: function (xhr) {
        submitBtn
          .prop("disabled", false)
          .html('<i class="bi bi-cloud-arrow-down me-1"></i>Download & Replace');
        var err = "Network error during database replacement.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          err = xhr.responseJSON.error;
        }
        alert(err);
      },
    });
  });

  // 5. Alter Column Default Feature
  function loadTablesDropdown(selectedTable) {
    var tableSelect = $("#alter-table-select");
    tableSelect.html('<option value="" disabled selected>Loading tables...</option>');

    $.ajax({
      url: "/api/database/tables",
      type: "GET",
      dataType: "json",
      success: function (resp) {
        if (resp.success && resp.tables) {
          tableSelect.empty();
          tableSelect.append('<option value="" disabled selected>Select a table...</option>');
          $.each(resp.tables, function (_, tbl) {
            tableSelect.append(
              $("<option></option>")
                .attr("value", tbl.name)
                .text(tbl.name + " (" + (tbl.row_count || 0).toLocaleString() + " rows)")
            );
          });
          if (selectedTable) {
            tableSelect.val(selectedTable).trigger("change");
          }
        }
      },
      error: function () {
        tableSelect.html('<option value="" disabled selected>Failed to load tables</option>');
      },
    });
  }

  // Open modal from header or row button
  $("#open-alter-column-btn").on("click", function () {
    loadTablesDropdown();
  });

  $(document).on("click", ".btn-alter-table-col", function () {
    var targetTable = $(this).data("table");
    loadTablesDropdown(targetTable);
    var modalEl = document.getElementById("alterColumnModal");
    var modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
    modal.show();
  });

  // Table selection changed -> load columns
  $("#alter-table-select").on("change", function () {
    var tableName = $(this).val();
    var colSelect = $("#alter-column-select");
    var helpText = $("#column-details-help");

    helpText.text("");
    colSelect.prop("disabled", true).html('<option value="" disabled selected>Loading columns...</option>');

    $.ajax({
      url: "/api/database/tables/" + encodeURIComponent(tableName) + "/columns",
      type: "GET",
      dataType: "json",
      success: function (resp) {
        if (resp.success && resp.columns) {
          colSelect.empty();
          colSelect.append('<option value="" disabled selected>Select a column...</option>');
          $.each(resp.columns, function (_, col) {
            var opt = $("<option></option>")
              .attr("value", col.name)
              .attr("data-type", col.type)
              .attr("data-default", col.default !== null ? col.default : "")
              .attr("data-nullable", col.nullable ? "1" : "0")
              .text(col.name + " (" + col.type + ")");
            colSelect.append(opt);
          });
          colSelect.prop("disabled", false);
        }
      },
      error: function () {
        colSelect.html('<option value="" disabled selected>Failed to load columns</option>');
      },
    });
  });

  // Column selection changed -> show current metadata & prefill default
  $("#alter-column-select").on("change", function () {
    var selectedOpt = $(this).find("option:selected");
    var colType = selectedOpt.data("type") || "";
    var currentDefault = selectedOpt.data("default");
    var nullable = selectedOpt.data("nullable") === "1" ? "Nullable" : "NOT NULL";

    var info = "Type: " + colType + " | " + nullable;
    if (currentDefault !== "" && currentDefault !== undefined) {
      info += " | Current default: " + currentDefault;
      $("#alter-default-input").val(currentDefault);
    } else {
      info += " | Current default: (none / NULL)";
      $("#alter-default-input").val("");
    }
    $("#column-details-help").text(info);
  });

  // Submit Alter Column Form
  $("#alter-column-form").on("submit", function (e) {
    e.preventDefault();
    var submitBtn = $("#alter-column-submit-btn");
    var alertBox = $("#alter-column-alert");
    var tableName = $("#alter-table-select").val();
    var columnName = $("#alter-column-select").val();
    var defaultValue = $("#alter-default-input").val();
    var backfill = $("#alter-backfill-check").is(":checked");

    if (!tableName || !columnName) {
      alertBox
        .removeClass("d-none alert-success")
        .addClass("alert-danger")
        .text("Please select both a table and a column.");
      return;
    }

    submitBtn.prop("disabled", true).html(
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Updating...'
    );
    alertBox.addClass("d-none");

    $.ajax({
      url: "/api/database/alter-column-default",
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify({
        table: tableName,
        column: columnName,
        default_value: defaultValue,
        backfill_existing: backfill,
      }),
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          alertBox
            .removeClass("d-none alert-danger")
            .addClass("alert-success")
            .html(
              '<i class="bi bi-check-circle me-1"></i>' +
              (resp.message || "Column updated successfully.") +
              (resp.backfilled_count !== undefined
                ? " (Backfilled rows: " + resp.backfilled_count + ")"
                : "")
            );
          // Reload column info
          $("#alter-table-select").trigger("change");
        } else {
          alertBox
            .removeClass("d-none alert-success")
            .addClass("alert-danger")
            .text(resp.error || "Failed to alter column.");
        }
      },
      error: function (xhr) {
        var err = "Network error updating column default.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          err = xhr.responseJSON.error;
        }
        alertBox
          .removeClass("d-none alert-success")
          .addClass("alert-danger")
          .text(err);
      },
      complete: function () {
        submitBtn
          .prop("disabled", false)
          .html('<i class="bi bi-check-lg me-1"></i>Update Column');
      },
    });
  });
});
