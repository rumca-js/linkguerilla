/**
 * YAFR Entries Interactive Client-Side Logic.
 * 
 * Handles AJAX interactions for voting, bookmarks, read later,
 * visit tracking, and dynamic alpha updates without page reload.
 */

$(document).ready(function () {

  // -------------------------------------------------------------------------
  // Search History & Autocomplete
  // -------------------------------------------------------------------------

  /** Minimum characters before autocomplete suggestions fire on keyup. */
  var AUTOCOMPLETE_MIN_CHARS = 1;

  /** Debounce timer for autocomplete keyup. */
  var _autocompleteTimer = null;

  /**
   * Populates and shows a search-history dropdown with the given suggestions.
   *
   * @param {jQuery} dropdown - The .search-history-dropdown element
   * @param {string[]} suggestions - Array of query strings
   * @param {string} headerText - Header label for the dropdown
   */
  function _renderSuggestions(dropdown, suggestions, headerText) {
    dropdown.empty();

    if (!suggestions || suggestions.length === 0) {
      dropdown.append(
        '<div class="dropdown-item text-muted disabled"><i class="bi bi-info-circle me-2"></i>No search history</div>'
      );
    } else {
      dropdown.append(
        '<div class="d-flex align-items-center justify-content-between px-3 py-2">' +
        '<h6 class="dropdown-header p-0 m-0"><i class="bi bi-clock-history me-1"></i>' + YafrUtils.escapeHtml(headerText) + '</h6>' +
        '<button type="button" class="btn btn-link btn-sm p-0 search-history-clear">Clear all</button>' +
        '</div>'
      );
      suggestions.forEach(function (query) {
        var escaped = YafrUtils.escapeHtml(query);
        dropdown.append(
          '<div class="d-flex align-items-center search-history-row">' +
          '<button type="button" class="dropdown-item search-history-item flex-grow-1 text-truncate" data-query="' + escaped + '">' +
          '<i class="bi bi-search me-2 text-secondary"></i>' + escaped +
          '</button>' +
          '<button type="button" class="btn btn-sm btn-link text-danger px-2 search-history-delete" data-query="' + escaped + '" title="Remove this search" aria-label="Remove this search">' +
          '<i class="bi bi-x-lg"></i></button></div>'
        );
      });
    }

    dropdown.addClass('show');
  }

  /**
   * Clock button: shows ALL recent searches (no prefix filter).
   */
  $(document).on('click', '.search-history-btn', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var btn = $(this);
    var inputSelector = btn.data('target');
    var input = $(inputSelector);
    var dropdown = input.closest('.position-relative').find('.search-history-dropdown');

    // Toggle: if already visible, hide it
    if (dropdown.hasClass('show')) {
      dropdown.removeClass('show');
      return;
    }

    // Hide any other open search history dropdowns
    $('.search-history-dropdown.show').removeClass('show');

    // Fetch the full retained search history (no prefix)
    $.ajax({
      url: '/api/history',
      type: 'GET',
      data: {},
      success: function (res) {
        var items = (res.success && res.data && res.data.suggestions) ? res.data.suggestions : [];
        _renderSuggestions(dropdown, items, 'Recent Searches');
      },
      error: function () {
        dropdown.empty().append(
          '<div class="dropdown-item text-muted disabled">Failed to load history</div>'
        );
        dropdown.addClass('show');
      }
    });
  });

  /**
   * Autocomplete on keyup: shows suggestions filtered by the current input text.
   */
  $(document).on('input', '#main-search-input, #compact-search-input', function () {
    var input = $(this);
    var dropdown = input.closest('.position-relative').find('.search-history-dropdown');
    var prefix = input.val().trim();

    // Clear previous debounce
    if (_autocompleteTimer) {
      clearTimeout(_autocompleteTimer);
    }

    // Hide if input is too short
    if (prefix.length < AUTOCOMPLETE_MIN_CHARS) {
      dropdown.removeClass('show');
      return;
    }

    // Debounce 250ms to avoid flooding the server
    _autocompleteTimer = setTimeout(function () {
      $.ajax({
        url: '/api/history/autocomplete',
        type: 'GET',
        data: { q: prefix },
        success: function (res) {
          var items = (res.success && res.data && res.data.suggestions) ? res.data.suggestions : [];
          if (items.length === 0) {
            dropdown.removeClass('show');
            return;
          }
          _renderSuggestions(dropdown, items, 'Suggestions');
        },
        error: function () {
          dropdown.removeClass('show');
        }
      });
    }, 250);
  });

  /**
   * When a search history item is clicked, populate the search input and submit.
   */
  $(document).on('click', '.search-history-item', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var query = $(this).data('query');
    var dropdown = $(this).closest('.search-history-dropdown');
    var form = $(this).closest('form');

    // If the dropdown is outside a form, find the nearest one
    if (!form.length) {
      form = dropdown.closest('.position-relative').find('input[name="q"]').closest('form');
    }

    var input = form.find('input[name="q"]');
    input.val(query);
    dropdown.removeClass('show');
    form.submit();
  });

  /** Remove one exact query (all duplicate occurrences) from history. */
  $(document).on('click', '.search-history-delete', function (e) {
    e.preventDefault();
    e.stopPropagation();
    var dropdown = $(this).closest('.search-history-dropdown');
    $.ajax({
      url: '/api/history/search',
      type: 'DELETE',
      contentType: 'application/json',
      data: JSON.stringify({ query: $(this).data('query') }),
      success: function (res) {
        if (res.success) {
          dropdown.removeClass('show');
          var target = dropdown.attr('id').replace('-history-dropdown', '-input');
          $('[data-target="#' + target + '"]').trigger('click');
        }
      }
    });
  });

  /** Clear all stored search history. */
  $(document).on('click', '.search-history-clear', function (e) {
    e.preventDefault();
    e.stopPropagation();
    var dropdown = $(this).closest('.search-history-dropdown');
    $.ajax({
      url: '/api/history',
      type: 'DELETE',
      success: function (res) {
        if (res.success) {
          _renderSuggestions(dropdown, [], 'Recent Searches');
        }
      }
    });
  });

  /**
   * Close search history dropdown when clicking elsewhere.
   */
  $(document).on('click', function (e) {
    if (!$(e.target).closest('.search-history-btn, .search-history-dropdown, #main-search-input, #compact-search-input').length) {
      $('.search-history-dropdown.show').removeClass('show');
    }
  });

  // -------------------------------------------------------------------------
  // Entry List Interactions
  // -------------------------------------------------------------------------

  // 0. Trigger Entry Detail View on Entry List Item Click
  $(document).on('click', '.entry-card-clickable, [data-detail-url]', function (e) {
    // If clicked on an interactive control (link, button, input), do not intercept
    if ($(e.target).closest('a, button, input, .btn, .btn-bookmark, .btn-set-vote, .btn-read-later, .badge').length) {
      return;
    }
    const detailUrl = $(this).data('detail-url');
    if (detailUrl) {
      window.location.href = detailUrl;
    }
  });

  // 1. Visit Tracking on Link Click
  $(document).on('click', '.entry-link', function () {
    const entryId = $(this).data('id');
    const card = $('#entry-card-' + entryId);

    // Dynamically mark as visited in UI
    if (card.length && !card.hasClass('entry-bookmarked') && !card.hasClass('entry-voted')) {
      card.addClass('entry-visited');
    }

    // Inform server of visit in background
    if (entryId) {
      $.ajax({
        url: '/api/entries/' + entryId + '/visit',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({})
      });
    }
  });

  // 2. Bookmark Toggle
  $(document).on('click', '.btn-bookmark', function (e) {
    e.preventDefault();
    e.stopPropagation();

    const btn = $(this);
    const entryId = btn.data('id');
    const card = $('#entry-card-' + entryId);

    if (!entryId) return;

    btn.prop('disabled', true);

    $.ajax({
      url: '/api/entries/' + entryId + '/bookmark',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({}),
      success: function (res) {
        if (res.success && res.data) {
          const isBookmarked = res.data.bookmarked;
          const icon = btn.find('i');

          if (isBookmarked) {
            icon.removeClass('bi-bookmark').addClass('bi-bookmark-fill');
            card.addClass('entry-bookmarked');
          } else {
            icon.removeClass('bi-bookmark-fill').addClass('bi-bookmark');
            card.removeClass('entry-bookmarked');
          }
        }
      },
      error: function (xhr) {
        console.error('Bookmark toggle failed:', xhr.responseText);
      },
      complete: function () {
        btn.prop('disabled', false);
      }
    });
  });

  // 3. Set Vote as a Number (-100 to 100)
  $(document).on('click', '.btn-set-vote', function (e) {
    e.preventDefault();
    e.stopPropagation();

    const btn = $(this);
    const entryId = btn.data('id');
    const scoreBadge = $('.score-badge[data-id="' + entryId + '"]');
    const currentVote = btn.data('current') !== undefined ? btn.data('current') : (scoreBadge.text().trim() || 0);

    if (!entryId) return;

    const userInput = prompt('Set vote rating (-100 to 100):', currentVote);
    if (userInput === null) return; // User cancelled

    const targetVote = parseInt(userInput.trim(), 10);
    if (isNaN(targetVote) || targetVote < -100 || targetVote > 100) {
      alert('Please enter a valid integer between -100 and 100.');
      return;
    }

    const card = $('#entry-card-' + entryId);
    btn.prop('disabled', true);

    $.ajax({
      url: '/api/entries/' + entryId + '/vote',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ vote: targetVote }),
      success: function (res) {
        if (res.success && res.data) {
          const newVotes = res.data.page_rating_votes;
          scoreBadge.text(newVotes);
          btn.data('current', newVotes);

          if (newVotes !== 0) {
            card.addClass('entry-voted');
          } else {
            card.removeClass('entry-voted');
          }
        }
      },
      error: function (xhr) {
        alert('Failed to set vote: ' + (xhr.responseJSON?.error || xhr.statusText));
      },
      complete: function () {
        btn.prop('disabled', false);
      }
    });
  });

  // 4. Read Later Toggle
  $(document).on('click', '.btn-read-later', function (e) {
    e.preventDefault();
    e.stopPropagation();

    const btn = $(this);
    const entryId = btn.data('id');

    if (!entryId) return;

    btn.prop('disabled', true);

    $.ajax({
      url: '/api/entries/' + entryId + '/read-later',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({}),
      success: function (res) {
        if (res.success && res.data) {
          const isSaved = res.data.read_later;
          const icon = btn.find('i');

          if (isSaved) {
            btn.addClass('active');
            icon.removeClass('bi-clock').addClass('bi-clock-fill');
          } else {
            btn.removeClass('active');
            icon.removeClass('bi-clock-fill').addClass('bi-clock');
          }
        }
      },
      error: function (xhr) {
        console.error('Read later toggle failed:', xhr.responseText);
      },
      complete: function () {
        btn.prop('disabled', false);
      }
    });
  });

  // 5. Copy Links to Clipboard in Entry List
  function _setCopiedState(btn, originalHtml) {
    btn.html('<i class="bi bi-check2 me-1"></i><span class="copy-text">Copied!</span>');
    btn.addClass('btn-success').removeClass('btn-outline-secondary');
    setTimeout(function () {
      btn.html(originalHtml);
      btn.removeClass('btn-success').addClass('btn-outline-secondary');
    }, 2000);
  }

  function _fallbackCopy(text, btn, originalHtml) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      _setCopiedState(btn, originalHtml);
    } catch (err) {
      console.error('Failed to copy links:', err);
    }
    document.body.removeChild(textarea);
  }

  $(document).on('click', '#btn-copy-links, .btn-copy-links', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var btn = $(this);
    var links = [];

    // Collect all links from entry elements with data-entry-url
    $('[data-entry-url]').each(function () {
      var url = $(this).attr('data-entry-url');
      if (url && links.indexOf(url) === -1) {
        links.push(url);
      }
    });

    // Fallback: if data-entry-url is not set, collect from entry external links
    if (links.length === 0) {
      $('.entry-external-link, .links-only-url').each(function () {
        var href = $(this).attr('href');
        if (href && href !== '#' && links.indexOf(href) === -1) {
          links.push(href);
        }
      });
    }

    if (links.length === 0) {
      return;
    }

    var text = links.join('\n');
    var originalHtml = btn.html();

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        _setCopiedState(btn, originalHtml);
      }).catch(function () {
        _fallbackCopy(text, btn, originalHtml);
      });
    } else {
      _fallbackCopy(text, btn, originalHtml);
    }
  });

});
