   Process                                                │ RSS
  ────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────
   process_jobs.py (worker)                               │ ~138 MB
   run.py (Flask, 2 threads)                              │ ~218 MB total
   main.py (supervisor)                                   │ ~106 MB

  Primary causes:

  1. 🔴 Heavy import chain — yt-dlp, webtoolkit, SQLAlchemy, BeautifulSoup, Flask etc. are loaded independently in
  each process. No memory sharing between processes.
  2. 🔴 Flask dev server (app.run()) is not production-safe — it spawns threads and shouldn't be used multi-
  instance. Switch to gunicorn (fork-based, CoW memory sharing) or waitress.
  3. 🟡 SQLAlchemy identity map accumulation in the worker loop — close_session() is never called between job
  iterations, so the ORM cache grows over the life of the worker.
  4. 🟡 get_shared_context() creates 3 repository objects + DB queries on every single HTTP request.

  Quickest fix: replace app.run() with gunicorn -w 2 — gunicorn pre-forks workers and they share the Python import
  footprint via copy-on-write, cutting per-instance RAM roughly in half. See the artifact for code-level
  recommendations.
                         


  ## Why 100-200MB Virtual Memory Is Expected

  Looking at your running processes:

    PID 6388:  128 MB VSZ (main.py)
    PID 6391:  136 MB VSZ (process_jobs.py)
    PID 6392:  130 MB VSZ (run.py)
    PID 6397:  204 MB VSZ (run.py - Werkzeug reloader child)

  Virtual memory (VSZ) ≠ actual RAM used. VSZ includes memory-mapped files, shared libraries, and reserved-but-not-
  yet-used space. The RSS (resident set) column is what's actually in RAM — your processes are using ~106–115 MB
  RSS, which is still expected.

  ### What's consuming that memory:

   Component                               │ Approx. impact
  ─────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────
   Python 3.12 runtime                     │ ~20–30 MB base
   Flask + Werkzeug                        │ ~5–10 MB
   SQLAlchemy + linkarchivetools           │ ~15–25 MB (ORM metadata, connection pools)
   yt-dlp                                  │ ~20–40 MB (massive library with many plugins/extractors loaded at
                                           │ import)
   requests + beautifulsoup4               │ ~5–10 MB
   Jinja2 + template cache                 │ ~5 MB
   Werkzeug dev server reloader (PID 6397) │ Forks a child process, doubles base cost

  ### The biggest culprit: yt-dlp

  yt-dlp is by far the heaviest dependency — it ships hundreds of site-specific extractors that are eagerly
  imported. This alone can add 20–40 MB to your process footprint.

  ### The reloader process (PID 6397)

  When running Flask in dev mode (run.py), Werkzeug spawns a child watcher process alongside the app — so you see
  two run.py entries. This is normal in development.
  ──────
  TL;DR: 100–200 MB virtual memory for a Python Flask app with SQLAlchemy + yt-dlp is completely expected and not a
  concern. It would only become an issue if you're deploying to a device with very limited RAM (< 256 MB total).
