/**
 * YAFR Client-Side Application Script
 */
document.addEventListener("DOMContentLoaded", function () {
  // 1. Theme Toggle (Light / Dark)
  const themeToggleBtn = document.getElementById("theme-toggle-btn");
  const themeIcon = document.getElementById("theme-icon");
  const themeText = document.getElementById("theme-text");
  const htmlElement = document.documentElement;

  // Read saved theme from localStorage or default to light
  const savedTheme = localStorage.getItem("yafr-theme") || "light";
  setTheme(savedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", function () {
      const currentTheme = htmlElement.getAttribute("data-bs-theme") || "light";
      const newTheme = currentTheme === "dark" ? "light" : "dark";
      setTheme(newTheme);
    });
  }

  function setTheme(theme) {
    htmlElement.setAttribute("data-bs-theme", theme);
    localStorage.setItem("yafr-theme", theme);

    if (themeIcon && themeText) {
      if (theme === "dark") {
        themeIcon.className = "bi bi-sun me-1";
        themeText.textContent = "Light";
      } else {
        themeIcon.className = "bi bi-moon-stars me-1";
        themeText.textContent = "Dark";
      }
    }
  }

  // 2. Network Status Monitor (Online / Offline)
  const networkBadge = document.getElementById("network-badge");

  function updateNetworkStatus() {
    if (!networkBadge) return;

    if (navigator.onLine) {
      networkBadge.className = "badge bg-success-subtle text-success border border-success-subtle px-2 py-1 rounded-pill";
      networkBadge.innerHTML = '<i class="bi bi-wifi me-1"></i>Online';
      networkBadge.title = "Network available";
    } else {
      networkBadge.className = "badge bg-secondary-subtle text-secondary border border-secondary-subtle px-2 py-1 rounded-pill";
      networkBadge.innerHTML = '<i class="bi bi-wifi-off me-1"></i>Offline';
      networkBadge.title = "Running in offline mode (local search active)";
    }
  }

  window.addEventListener("online", updateNetworkStatus);
  window.addEventListener("offline", updateNetworkStatus);
  updateNetworkStatus();

  // 3. Remote WebTools Server Status Monitor
  const webtoolsBadge = document.getElementById("webtools-badge");

  function updateWebToolsStatus() {
    if (!webtoolsBadge) return;

    if (!navigator.onLine) {
      if (!webtoolsBadge.classList.contains("d-none")) {
        webtoolsBadge.className = "badge bg-secondary-subtle text-secondary border border-secondary-subtle px-2 py-1 rounded-pill";
        webtoolsBadge.innerHTML = '<i class="bi bi-hdd-network me-1"></i>WebTools (Offline)';
        webtoolsBadge.title = "Client network is offline";
      }
      return;
    }

    fetch("/api/config/webtools-status")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.configured) {
          webtoolsBadge.classList.add("d-none");
          return;
        }

        webtoolsBadge.classList.remove("d-none");
        if (data.online) {
          webtoolsBadge.className = "badge bg-success-subtle text-success border border-success-subtle px-2 py-1 rounded-pill";
          webtoolsBadge.innerHTML = '<i class="bi bi-hdd-network me-1"></i>WebTools';
          webtoolsBadge.title = "Remote WebTools server is online (" + data.url + ")";
        } else {
          webtoolsBadge.className = "badge bg-danger-subtle text-danger border border-danger-subtle px-2 py-1 rounded-pill";
          webtoolsBadge.innerHTML = '<i class="bi bi-hdd-network me-1"></i>WebTools Offline';
          webtoolsBadge.title = "Remote WebTools server is unreachable (" + data.url + "). Falling back to local BaseUrl.";
        }
      })
      .catch(function () {
        // Silently catch to avoid noisy console errors on transient network issues
      });
  }

  updateWebToolsStatus();
  window.addEventListener("online", updateWebToolsStatus);

  // 4. Background Worker Liveness Monitor (polls /api/status/worker every 60s)
  const workerBadge = document.getElementById("worker-badge");

  function updateWorkerStatus() {
    if (!workerBadge) return;

    fetch("/api/status/worker")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || data.visible === false) {
          workerBadge.classList.add("d-none");
          return;
        }

        workerBadge.classList.remove("d-none");
        var isWorkerActive = data.is_active !== undefined ? data.is_active : data.active;

        if (isWorkerActive) {
          workerBadge.className = "badge bg-success-subtle text-success border border-success-subtle px-2 py-1 rounded-pill";
          var ago = data.age_seconds !== null && data.age_seconds !== undefined ? " (" + data.age_seconds + "s ago)" : "";
          workerBadge.innerHTML = '<i class="bi bi-cpu me-1"></i>Worker';
          workerBadge.title = "Background worker is active" + ago + ". Thread: " + (data.thread_id || "?");
        } else {
          workerBadge.className = "badge bg-danger-subtle text-danger border border-danger-subtle px-2 py-1 rounded-pill";
          workerBadge.innerHTML = '<i class="bi bi-cpu me-1"></i>Worker Dead';
          workerBadge.title = data.message || "Background worker is dead or not running.";
        }
      })
      .catch(function () {
        if (workerBadge.classList.contains("d-none")) {
          return;
        }
        workerBadge.className = "badge bg-warning-subtle text-warning border border-warning-subtle px-2 py-1 rounded-pill";
        workerBadge.innerHTML = '<i class="bi bi-cpu me-1"></i>Worker ?';
        workerBadge.title = "Could not contact worker status endpoint.";
      });
  }

  updateWorkerStatus();
  setInterval(updateWorkerStatus, 60000);

  // 5. Global Bootstrap Popovers and Tooltips Initialization
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
});
