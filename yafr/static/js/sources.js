/**
 * Sources View Interactions for YAFR.
 *
 * Implements multi-select batch deletion and refresh, single source enable/disable toggling,
 * single source fetch triggers, modal confirmations, and live polling of source update progress.
 */

$(document).ready(function() {
  let pollInterval = null;

  // -------------------------------------------------------------
  // 1. Multi-Select Handling
  // -------------------------------------------------------------
  function updateBatchControls() {
    const checkedBoxes = $('.source-select-check:checked');
    const count = checkedBoxes.length;

    $('#batch-selected-count').text(count);
    $('#batch-refresh-count').text(count);
    $('#batch-delete-count-display').text(count);

    if (count > 0) {
      $('#btn-batch-delete').removeClass('d-none');
      $('#btn-batch-refresh').removeClass('d-none');
    } else {
      $('#btn-batch-delete').addClass('d-none');
      $('#btn-batch-refresh').addClass('d-none');
    }
  }

  // Master "Select All" Checkbox
  $('#select-all-sources').on('change', function() {
    const isChecked = $(this).is(':checked');
    $('.source-select-check').prop('checked', isChecked);
    updateBatchControls();
  });

  // Individual Row Checkbox Change
  $(document).on('change', '.source-select-check', function() {
    const allCount = $('.source-select-check').length;
    const checkedCount = $('.source-select-check:checked').length;
    $('#select-all-sources').prop('checked', allCount > 0 && allCount === checkedCount);
    updateBatchControls();
  });

  // Batch Delete Confirmation Click
  $('#confirm-batch-delete-btn').on('click', function() {
    const btn = $(this);
    const sourceIds = $('.source-select-check:checked').map(function() {
      return parseInt($(this).val(), 10);
    }).get();

    if (!sourceIds.length) return;

    btn.prop('disabled', true).text('Deleting...');

    $.ajax({
      url: '/api/sources/batch-delete',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ source_ids: sourceIds }),
      success: function(resp) {
        btn.prop('disabled', false).text('Delete Selected');
        const modalEl = document.getElementById('batchDeleteModal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();

        if (resp.success) {
          // Remove rows from DOM
          sourceIds.forEach(function(id) {
            $(`#source-row-${id}`).fadeOut(300, function() {
              $(this).remove();
            });
          });
          updateBatchControls();
        } else {
          alert('Batch delete failed: ' + (resp.error || 'Unknown error'));
        }
      },
      error: function(xhr) {
        btn.prop('disabled', false).text('Delete Selected');
        alert('Batch delete request failed: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  // Batch Refresh Click
  $('#btn-batch-refresh').on('click', function() {
    const sourceIds = $('.source-select-check:checked').map(function() {
      return parseInt($(this).val(), 10);
    }).get();

    if (!sourceIds.length) return;

    $.ajax({
      url: '/api/sources/fetch-all',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ source_ids: sourceIds, include_errors: true }),
      success: function(resp) {
        if (resp.success) {
          startProgressPolling();
        } else {
          alert('Batch refresh failed: ' + (resp.error || 'Unknown error'));
        }
      },
      error: function(xhr) {
        alert('Batch refresh failed: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  // -------------------------------------------------------------
  // 2. Single Source Actions: Delete, Toggle Enable, Fetch
  // -------------------------------------------------------------
  let singleDeleteId = null;

  // Click Delete button on a row
  $(document).on('click', '.btn-delete-single', function() {
    singleDeleteId = $(this).data('source-id');
    const title = $(this).data('source-title');
    $('#delete-source-title-display').text(title || `Source #${singleDeleteId}`);
    const modal = new bootstrap.Modal(document.getElementById('deleteSourceModal'));
    modal.show();
  });

  // Confirm Single Delete
  $('#confirm-delete-source-btn').on('click', function() {
    if (!singleDeleteId) return;
    const btn = $(this);
    btn.prop('disabled', true).text('Deleting...');

    $.ajax({
      url: `/api/sources/${singleDeleteId}`,
      method: 'DELETE',
      success: function(resp) {
        btn.prop('disabled', false).text('Delete Source');
        const modalEl = document.getElementById('deleteSourceModal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();

        if (resp.success) {
          $(`#source-row-${singleDeleteId}`).fadeOut(300, function() {
            $(this).remove();
            updateBatchControls();
          });
        }
      },
      error: function(xhr) {
        btn.prop('disabled', false).text('Delete Source');
        alert('Delete failed: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  // Toggle Enable / Disable
  $(document).on('click', '.btn-toggle-enable', function() {
    const btn = $(this);
    const sourceId = btn.data('source-id');
    const isCurrentlyEnabled = btn.data('enabled') === 'true' || btn.data('enabled') === true;
    const endpoint = isCurrentlyEnabled ? `/api/sources/${sourceId}/disable` : `/api/sources/${sourceId}/enable`;
    const card = $(`#source-row-${sourceId}`);

    btn.prop('disabled', true);

    $.ajax({
      url: endpoint,
      method: 'POST',
      contentType: 'application/json',
      success: function(resp) {
        btn.prop('disabled', false);
        if (resp.success) {
          const newState = resp.enabled;
          btn.data('enabled', newState ? 'true' : 'false');

          if (newState) {
            btn.html('<i class="bi bi-toggle-on text-success"></i>');
            btn.attr('title', 'Disable source');
            card.removeClass('source-disabled').css('opacity', '1.0');
          } else {
            btn.html('<i class="bi bi-toggle-off text-muted"></i>');
            btn.attr('title', 'Enable source');
            card.addClass('source-disabled').css('opacity', '0.4');
          }
        }
      },
      error: function(xhr) {
        btn.prop('disabled', false);
        alert('Failed to toggle source state: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  // Single Source Fetch Trigger — enqueues a process-source background job
  $(document).on('click', '.btn-fetch-single', function() {
    const btn = $(this);
    const icon = btn.find('i');
    const sourceId = btn.data('source-id');

    btn.prop('disabled', true);
    icon.addClass('spin');

    $.ajax({
      url: `/api/sources/${sourceId}/fetch`,
      method: 'POST',
      contentType: 'application/json',
      success: function(resp) {
        btn.prop('disabled', false);
        icon.removeClass('spin');
        if (resp.success) {
          // Job enqueued — brief visual confirmation, no blocking reload
          icon.removeClass().addClass('bi bi-check-circle text-success');
          setTimeout(function() {
            icon.removeClass().addClass('bi bi-arrow-clockwise');
          }, 2500);
        } else {
          alert('Could not queue fetch: ' + (resp.message || resp.error || 'Failed to enqueue source fetch'));
        }
      },
      error: function(xhr) {
        btn.prop('disabled', false);
        icon.removeClass('spin');
        alert('Fetch failed: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  // -------------------------------------------------------------
  // 3. Batch Outdated Fetch & Progress Bar Polling
  // -------------------------------------------------------------
  $('#confirm-fetch-outdated-btn').on('click', function() {
    const includeErrors = $('#modal-include-errors').is(':checked');
    const modalEl = document.getElementById('fetchOutdatedModal');
    const modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) modal.hide();

    $('#main-fetch-spinner, #top-fetch-spinner').addClass('spin');

    $.ajax({
      url: '/api/sources/fetch-all',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ include_errors: includeErrors }),
      success: function(resp) {
        if (resp.success && resp.queued_sources_count > 0) {
          startProgressPolling();
        } else {
          $('#main-fetch-spinner, #top-fetch-spinner').removeClass('spin');
          alert(resp.message || 'No sources required refresh.');
        }
      },
      error: function(xhr) {
        $('#main-fetch-spinner, #top-fetch-spinner').removeClass('spin');
        alert('Failed to initiate batch refresh: ' + (xhr.responseJSON?.error || xhr.statusText));
      }
    });
  });

  function startProgressPolling() {
    const container = $('#refresh-progress-container');
    const bar = $('#refresh-progress-bar');
    const title = $('#refresh-progress-title');
    const countLabel = $('#refresh-progress-count');

    container.removeClass('d-none');
    $('#main-fetch-spinner, #top-fetch-spinner').addClass('spin');

    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(function() {
      $.ajax({
        url: '/api/sources/refresh-status',
        method: 'GET',
        cache: false,
        success: function(status) {
          if (!status) return;

          const pct = Math.min(100, Math.max(0, status.percentage || 0));
          bar.css('width', `${pct}%`).attr('aria-valuenow', pct);

          if (status.current_source_title) {
            title.text(`Updating: ${status.current_source_title}`);
          }
          countLabel.text(`${status.completed_sources || 0} / ${status.total_sources || 0}`);

          if (!status.is_running) {
            clearInterval(pollInterval);
            pollInterval = null;
            $('#main-fetch-spinner, #top-fetch-spinner').removeClass('spin');
            title.text('Update complete!');
            bar.removeClass('progress-bar-animated bg-primary').addClass('bg-success');

            setTimeout(function() {
              location.reload();
            }, 1200);
          }
        },
        error: function() {
          clearInterval(pollInterval);
          pollInterval = null;
          $('#main-fetch-spinner, #top-fetch-spinner').removeClass('spin');
        }
      });
    }, 1000);
  }

  // -------------------------------------------------------------
  // 5. Batch Add Sources Modal
  // -------------------------------------------------------------
  const batchAddModal = document.getElementById('batchAddSourcesModal');

  // Live URL counter
  $('#batch-add-sources-urls').on('input', function() {
    const lines = $(this).val().split('\n').filter(l => l.trim().length > 0);
    const count = Math.min(lines.length, 100);
    $('#batch-add-sources-counter').text(`${count} / 100 URLs`);
  });

  // Reset modal on close
  if (batchAddModal) {
    batchAddModal.addEventListener('hidden.bs.modal', function() {
      $('#batch-add-sources-form')[0].reset();
      $('#batch-add-sources-counter').text('0 / 100 URLs');
      $('#batch-add-sources-alert').addClass('d-none').text('');
    });
  }

  // Submit batch add
  $('#batch-add-sources-form').on('submit', function(e) {
    e.preventDefault();

    const rawText = $('#batch-add-sources-urls').val();
    const sourceType = $('#batch-add-sources-type').val().trim();

    const urls = rawText.split('\n')
      .map(l => l.trim())
      .filter(l => l.length > 0)
      .slice(0, 100);

    if (!urls.length) return;

    const sources = urls.map(url => {
      const item = { url };
      if (sourceType) item.source_type = sourceType;
      return item;
    });

    const submitBtn = $('#batch-add-sources-submit-btn');
    const spinner = submitBtn.find('.spinner-border');
    submitBtn.prop('disabled', true);
    spinner.removeClass('d-none');

    const alertBox = $('#batch-add-sources-alert');
    alertBox.addClass('d-none').removeClass('alert-success alert-danger alert-warning').text('');

    $.ajax({
      url: '/api/sources/batch-add',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ sources }),
      success: function(resp) {
        submitBtn.prop('disabled', false);
        spinner.addClass('d-none');

        if (resp.success) {
          let cls = 'alert-success';
          if (resp.added_count === 0) cls = 'alert-warning';
          alertBox.removeClass('d-none').addClass(cls).text(resp.message);
          if (resp.added_count > 0) {
            setTimeout(function() {
              const modal = bootstrap.Modal.getInstance(batchAddModal);
              if (modal) modal.hide();
              location.reload();
            }, 1500);
          }
        } else {
          alertBox.removeClass('d-none').addClass('alert-danger').text(resp.error || 'Failed to add sources.');
        }
      },
      error: function(xhr) {
        submitBtn.prop('disabled', false);
        spinner.addClass('d-none');
        const msg = xhr.responseJSON?.error || xhr.statusText || 'Request failed';
        alertBox.removeClass('d-none').addClass('alert-danger').text(msg);
      }
    });
  });

  // Check if a background refresh is already running on page load
  $.ajax({
    url: '/api/sources/refresh-status',
    method: 'GET',
    cache: false,
    success: function(status) {
      if (status && status.is_running) {
        startProgressPolling();
      }
    }
  });

  // -------------------------------------------------------------
  // 4. Touch Pull-To-Refresh Simulation
  // -------------------------------------------------------------
  let touchStartY = 0;
  window.addEventListener('touchstart', function(e) {
    if (window.scrollY === 0) {
      touchStartY = e.touches[0].clientY;
    } else {
      touchStartY = 0;
    }
  }, { passive: true });

  window.addEventListener('touchend', function(e) {
    if (touchStartY > 0) {
      const touchEndY = e.changedTouches[0].clientY;
      if (touchEndY - touchStartY > 120 && window.scrollY === 0) {
        location.reload();
      }
    }
  }, { passive: true });

});
