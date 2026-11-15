/**
 * YAFR Logs View Client-Side Script
 *
 * Handles individual log deletion and bulk clear operations
 * via AJAX calls to the JSON API.
 */
document.addEventListener("DOMContentLoaded", function () {

  // 1. Delete Individual Log Entry
  $(document).on("click", ".delete-log-btn", function () {
    var btn = $(this);
    var logId = btn.data("log-id");
    if (!logId) return;

    $.ajax({
      url: "/api/logs/" + logId,
      type: "DELETE",
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          $("#log-row-" + logId).fadeOut(300, function () {
            $(this).remove();
            // If table is now empty, reload to show empty state
            if ($("#logs-table-body tr").length === 0) {
              window.location.reload();
            }
          });
        } else {
          alert("Failed to delete log entry: " + (resp.error || "Unknown error"));
        }
      },
      error: function () {
        alert("Network error while deleting log entry.");
      }
    });
  });

  // 2. Clear Logs Modal Setup
  $("#clearLogsModal").on("show.bs.modal", function (event) {
    var triggerBtn = $(event.relatedTarget);
    var level = triggerBtn.data("clear-level") || "all";
    var name = triggerBtn.data("clear-name") || "All";

    var confirmBtn = $("#confirm-clear-logs-btn");
    confirmBtn.data("clear-level", level);
    confirmBtn.data("clear-name", name);

    if (level === "all") {
      $("#clear-modal-title").text("Clear All Logs");
      $("#clear-modal-body-text").html(
        "Are you sure you want to permanently delete <strong>all</strong> log entries?"
      );
      $("#clear-modal-warning-text").text(
        "This operation cannot be undone. All application log history will be lost."
      );
      $("#confirm-clear-btn-text").text("Clear All Logs");
    } else {
      var upperName = name.toUpperCase();
      $("#clear-modal-title").text("Clear " + name + " Logs");
      $("#clear-modal-body-text").html(
        "Are you sure you want to permanently delete all <strong>" +
          upperName +
          "</strong> log entries?"
      );
      $("#clear-modal-warning-text").text(
        "This operation cannot be undone. All " +
          upperName +
          " log history will be lost."
      );
      $("#confirm-clear-btn-text").text("Clear " + name + " Logs");
    }
  });

  // 3. Confirm Clear Logs (AJAX)
  $("#confirm-clear-logs-btn").on("click", function () {
    var btn = $(this);
    var level = btn.data("clear-level") || "all";
    var name = btn.data("clear-name") || "All";
    var originalHtml = btn.html();

    btn.prop("disabled", true).html(
      '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Clearing...'
    );

    var postData = {};
    if (level && level !== "all") {
      postData.level = level;
    }

    $.ajax({
      url: "/api/logs/clear",
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify(postData),
      dataType: "json",
      success: function (resp) {
        if (resp.success) {
          var currentUrl = new URL(window.location.href);
          if (currentUrl.searchParams.has("page")) {
            currentUrl.searchParams.delete("page");
            window.location.href = currentUrl.toString();
          } else {
            window.location.reload();
          }
        } else {
          btn.prop("disabled", false).html(originalHtml);
          alert("Failed to clear logs: " + (resp.error || "Unknown error"));
        }
      },
      error: function () {
        btn.prop("disabled", false).html(originalHtml);
        alert("Network error while clearing logs.");
      }
    });
  });
});
