# LinkGuerilla

> **Repository:** [rumca-js/linkguerilla](https://github.com/rumca-js/linkguerilla)  
> **Docker Hub:** [rozbujnik/linkguerilla](https://hub.docker.com/r/rozbujnik/linkguerilla) *(Docker build coming soon)*

**LinkGuerilla** private, self-hosted link bunker and curation engine

Instead of relying on third-party platforms, LinkGuerilla puts you in total control of your data. Aggregate RSS feeds, ingest links directly from IMAP emails, build custom music playlists, log movie watchlists, tag content, and rank entries with weighted voting—all backed by a minimal, ultra-portable database tailored to your needs.

Technology stack: HTML/css/javascript/bootstrapp/python/flask

---

## Highlights

- **Multi-Source Ingestion** — Pull entries automatically via RSS, parse links from IMAP emails, or add items manually.
- **Weighted Ratings & Votes** — Assign custom scores and weights to prioritize music, movies, articles, or resources.
- **Tagging & Curation** — Tag entries for effortless categorization and custom playlist or list generation.
- **Full-Text Search** — Instantly query and filter entries by link URL, title, description, or metadata.
- **Instance Flexibility** — Spin up distinct, dedicated instances configured for specific topics (e.g., music curation, news archiving, film logs).
- **SQLite Core** — Data is maintained by a simple SQLite database. Easy to share, reuse, and convert

---

## Quick Start

### Local Development

Run the application locally using the standard Makefile command:

```bash
make run
```
