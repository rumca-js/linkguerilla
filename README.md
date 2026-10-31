# LinkGuerilla

> **Repository:** [rumca-js/yafr_next](https://github.com/rumca-js/yafr_next)  
> **Docker Hub:** [rozbujnik/yafr](https://hub.docker.com/r/rozbujnik/yafr) *(Docker build coming soon)*

**LinkGuerilla** is an agile, self-hosted link bunker and curation engine built to break free from Big Tech algorithms, walled gardens, and centralized feeds.

Instead of relying on third-party platforms, LinkGuerilla puts you in total control of your data. Aggregate RSS feeds, ingest links directly from IMAP emails, build custom music playlists, log movie watchlists, tag content, and rank entries with weighted voting—all backed by a minimal, ultra-portable database tailored to your needs.

---

## Highlights

- **Multi-Source Ingestion** — Pull entries automatically via RSS, parse links from IMAP emails, or add items manually.
- **Weighted Ratings & Votes** — Assign custom scores and weights to prioritize music, movies, articles, or resources.
- **Tagging & Curation** — Tag entries for effortless categorization and custom playlist or list generation.
- **Full-Text Search** — Instantly query and filter entries by link URL, title, description, or metadata.
- **Instance Flexibility** — Spin up distinct, dedicated instances configured for specific topics (e.g., music curation, news archiving, film logs).
- **SQLite Core** — Single-file database architecture makes backups, migrations, and offline archiving dead simple.

---

## Quick Start

### Local Development

Run the application locally using the standard Makefile command:

```bash
make run
```
