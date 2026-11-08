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
                         
