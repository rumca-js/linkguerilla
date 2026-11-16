/**
 * YAFR Quick Add Link and Live Validation Logic.
 * 
 * Provides interactive URL validation, clickable proposition buttons,
 * single-entry quick creation, and batch link ingestion.
 */

$(document).ready(function () {
  let validateTimeout = null;

  // 1. Debounced Validation for Quick Add URL Input
  $('#quick-add-url, #link').on('input paste', function () {
    const inputEl = $(this);
    clearTimeout(validateTimeout);

    validateTimeout = setTimeout(function () {
      handleUrlValidation(inputEl);
    }, 250);
  });

  // Also validate on blur immediately
  $('#quick-add-url, #link').on('blur', function () {
    clearTimeout(validateTimeout);
    handleUrlValidation($(this));
  });

  // 2. Sync Preview button href with URL input
  function updatePreviewHref() {
    const url = $('#quick-add-url').val().trim();
    const btn = $('#quick-add-preview-btn');
    if (url) {
      btn.attr('href', '/preview?url=' + encodeURIComponent(url));
    } else {
      btn.attr('href', '/preview');
    }
  }

  $('#quick-add-url').on('input paste change', function () {
    updatePreviewHref();
  });

  // 2b. Paste from Clipboard Button
  $('#quick-add-paste-btn').on('click', async function () {
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (text) {
          $('#quick-add-url').val(text.trim());
          handleUrlValidation($('#quick-add-url'));
          updatePreviewHref();
        }
      }
    } catch (err) {
      console.warn('Clipboard read failed:', err);
    }
  });

  // 3. Proposition Chip Click Handler (Replaces Input with Suggested URL)
  $(document).on('click', '.proposition-btn', function (e) {
    e.preventDefault();
    const suggestedUrl = $(this).data('url');
    const targetInput = $(this).closest('form').find('input[type="text"], input[type="url"]').first();

    if (suggestedUrl && targetInput.length) {
      targetInput.val(suggestedUrl);
      handleUrlValidation(targetInput);
    }
  });

  /**
   * Performs AJAX call to /api/entries/validate-link and renders propositions/alerts.
   */
  function handleUrlValidation(inputEl) {
    const rawVal = inputEl.val() || '';
    const trimmed = rawVal.trim();

    // Auto-trim input field value if it had leading/trailing whitespace
    if (rawVal !== trimmed) {
      inputEl.val(trimmed);
    }

    const form = inputEl.closest('form');
    const propContainer = form.find('#quick-add-propositions-container, #propositions-container');
    const propList = form.find('#quick-add-propositions, #propositions-list');
    const alertBox = form.find('#quick-add-alert, #validation-alert');

    if (!trimmed) {
      if (propContainer.length) propContainer.addClass('d-none');
      if (alertBox.length) alertBox.addClass('d-none').empty();
      return;
    }

    $.ajax({
      url: '/api/entries/validate-link',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ url: trimmed }),
      success: function (res) {
        if (!res.success || !res.data) return;

        const data = res.data;

        // Render Clickable Proposition Badges
        if (propContainer.length && propList.length) {
          propList.empty();

          if (data.propositions && data.propositions.length > 0) {
            data.propositions.forEach(function (prop) {
              const chip = $(
                '<button type="button" class="btn btn-outline-primary btn-sm rounded-pill proposition-btn me-1 mb-1 shadow-sm">' +
                '<i class="bi bi-arrow-right-short me-1"></i>' +
                '<strong>' + $('<div>').text(prop.label).html() + ':</strong> ' +
                '<span class="text-secondary small ms-1">' + $('<div>').text(prop.url).html() + '</span>' +
                '</button>'
              );
              chip.data('url', prop.url);
              propList.append(chip);
            });
            propContainer.removeClass('d-none');
          } else {
            propContainer.addClass('d-none');
          }
        }

        // Render Alerts / Validation Status
        if (alertBox.length) {
          alertBox.removeClass('alert-danger alert-warning alert-success d-none');

          if (!data.is_web_link) {
            alertBox
              .addClass('alert-danger')
              .html('<i class="bi bi-exclamation-triangle-fill me-2"></i>Invalid link: only web protocols (HTTP/HTTPS) are supported.');
          } else if (data.is_duplicate) {
            alertBox
              .addClass('alert-warning')
              .html('<i class="bi bi-info-circle-fill me-2"></i><strong>Duplicate entry:</strong> This URL is already saved in your database.');
          } else if (!data.allowed) {
            alertBox
              .addClass('alert-warning')
              .html('<i class="bi bi-shield-exclamation me-2"></i><strong>Policy restriction:</strong> ' +
                    $('<div>').text(data.rejection_reason || 'Link violates configured policy.').html() +
                    '<div class="mt-1 small">Check "Override link policies" to allow inserting anyway.</div>');
          } else {
            alertBox
              .addClass('alert-success')
              .html('<i class="bi bi-check-circle-fill me-2"></i>Valid URL link.');
          }
        }
      },
      error: function (xhr) {
        if (alertBox.length) {
          alertBox
            .removeClass('alert-success alert-warning d-none')
            .addClass('alert-danger')
            .text(xhr.responseJSON?.error || 'Validation error.');
        }
      }
    });
  }

  // 4. Submit Single Quick Add Form
  $('#quick-add-single-form').on('submit', function (e) {
    e.preventDefault();

    const form = $(this);
    const submitBtn = $('#quick-add-submit-btn');
    const spinner = submitBtn.find('.spinner-border');
    const alertBox = $('#quick-add-alert');

    const rawUrl = $('#quick-add-url').val() || '';
    const link = rawUrl.trim();
    if (!link) return;

    const title = ($('#quick-add-title').val() || '').trim();
    const description = ($('#quick-add-description').val() || '').trim();
    const tagsStr = ($('#quick-add-tags').val() || '').trim();
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim().replace(/^#/, '')).filter(Boolean) : [];
    const readLater = $('#quick-add-read-later').is(':checked');
    const ignorePolicy = $('#quick-add-ignore-policy').is(':checked');

    submitBtn.prop('disabled', true);
    spinner.removeClass('d-none');

    $.ajax({
      url: '/api/entries/quick-add',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({
        link: link,
        title: title,
        description: description,
        tags: tags,
        read_later: readLater,
        ignore_policy: ignorePolicy
      }),
      success: function (res) {
        if (res.success && res.data) {
          alertBox
            .removeClass('alert-danger alert-warning d-none')
            .addClass('alert-success')
            .html('<i class="bi bi-check-circle-fill me-2"></i><strong>Entry Added!</strong> <a href="/entries/' + res.data.entry_id + '" class="alert-link ms-2">View details &rarr;</a>');

          form[0].reset();
          $('#quick-add-propositions-container').addClass('d-none');

          // Auto-close modal after 1.5 seconds if on entries page
          setTimeout(function () {
            const modalEl = document.getElementById('quickAddLinkModal');
            if (modalEl) {
              const modalInstance = bootstrap.Modal.getInstance(modalEl);
              if (modalInstance) modalInstance.hide();
            }
            if (window.location.pathname === '/' || window.location.pathname === '/entries') {
              window.location.reload();
            }
          }, 1200);
        }
      },
      error: function (xhr) {
        alertBox
          .removeClass('alert-success alert-warning d-none')
          .addClass('alert-danger')
          .html('<i class="bi bi-exclamation-triangle-fill me-2"></i>' + (xhr.responseJSON?.error || 'Failed to add entry.'));
      },
      complete: function () {
        submitBtn.prop('disabled', false);
        spinner.addClass('d-none');
      }
    });
  });

  // 5. Batch Links Counter and Formatting
  $('#quick-add-batch-urls').on('input', function () {
    const text = $(this).val() || '';
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    const count = lines.length;
    const counterBadge = $('#quick-add-batch-counter');

    counterBadge.text(count + ' / 200 links');
    if (count > 200) {
      counterBadge.removeClass('bg-secondary-subtle text-secondary-emphasis').addClass('bg-danger text-white');
    } else {
      counterBadge.removeClass('bg-danger text-white').addClass('bg-secondary-subtle text-secondary-emphasis');
    }
  });

  // 6. Submit Batch Add Form
  $('#quick-add-batch-form').on('submit', function (e) {
    e.preventDefault();

    const submitBtn = $('#quick-add-batch-submit-btn');
    const spinner = submitBtn.find('.spinner-border');
    const alertBox = $('#quick-add-batch-alert');

    const text = $('#quick-add-batch-urls').val() || '';
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

    if (!lines.length) {
      alert('Please enter at least one URL link.');
      return;
    }

    const candidateLinks = lines.slice(0, 200);
    const tagsStr = ($('#quick-add-batch-tags').val() || '').trim();
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim().replace(/^#/, '')).filter(Boolean) : [];
    const readLater = $('#quick-add-batch-read-later').is(':checked');
    const ignorePolicy = $('#quick-add-batch-ignore-policy').is(':checked');

    submitBtn.prop('disabled', true);
    spinner.removeClass('d-none');

    $.ajax({
      url: '/api/entries/batch-add',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({
        links: candidateLinks,
        tags: tags,
        read_later: readLater,
        ignore_policy: ignorePolicy
      }),
      success: function (res) {
        if (res.success && res.data) {
          const d = res.data;
          alertBox
            .removeClass('alert-danger alert-warning d-none')
            .addClass('alert-success')
            .html(
              '<i class="bi bi-check-circle-fill me-2"></i>' +
              '<strong>Batch processed:</strong> Added ' + d.added_count + ' entries ' +
              '(' + d.duplicate_count + ' duplicates skipped, ' + d.rejected_count + ' rejected).'
            );

          $('#quick-add-batch-urls').val('');
          $('#quick-add-batch-counter').text('0 / 200 links');

          setTimeout(function () {
            if (window.location.pathname === '/' || window.location.pathname === '/entries') {
              window.location.reload();
            }
          }, 1500);
        }
      },
      error: function (xhr) {
        alertBox
          .removeClass('alert-success alert-warning d-none')
          .addClass('alert-danger')
          .html('<i class="bi bi-exclamation-triangle-fill me-2"></i>' + (xhr.responseJSON?.error || 'Batch import failed.'));
      },
      complete: function () {
        submitBtn.prop('disabled', false);
        spinner.addClass('d-none');
      }
    });
  });

  // Autofocus link input on modal open and tab switch
  const quickAddModal = document.getElementById('quickAddLinkModal');
  if (quickAddModal) {
    quickAddModal.addEventListener('shown.bs.modal', function () {
      if ($('#batch-link-pane').hasClass('active')) {
        $('#quick-add-batch-urls').trigger('focus');
      } else {
        $('#quick-add-url').trigger('focus');
      }
    });
  }

  $('#single-link-tab').on('shown.bs.tab', function () {
    $('#quick-add-url').trigger('focus');
  });

  $('#batch-link-tab').on('shown.bs.tab', function () {
    $('#quick-add-batch-urls').trigger('focus');
  });

});
