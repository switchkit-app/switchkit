# Switch Kit v0.1.3

**Plex → Jellyfin migration readiness inspector.**

Opens your Plex database **read-only** and exports what would transfer. No writes. No network. No account. Do not share the generated report unredacted — it contains viewing history.

## Quick Start

```bash
# Docker (recommended — mounts read-only)
docker run --rm \
  -v /path/to/plex/db:/plex:ro \
  -v $(pwd):/output \
  ghcr.io/switchkit/switchkit \
  inspect --plex-db /plex/com.plexapp.plugins.library.db --output /output/plan.json

# CLI
pip install switchkit
switchkit inspect --plex-db /var/lib/plex/db/com.plexapp.plugins.library.db
```

## What v0.1.0 Does

| Feature | Status |
|---------|--------|
| Plex library inventory (Movies, TV, Music) | ✅ |
| Watch history extraction | ✅ |
| Ratings extraction | ✅ |
| Resume position extraction | ✅ |
| User account listing (local + external) | ✅ |
| Collection inventory | ✅ |
| GUID format diagnostics (legacy vs modern) | ✅ |
| **Jellyfin write mode** | 🚧 Not built yet |
| **Backup/rollback** | 🚧 Not built yet |

## Limitations

- **Does not write to Jellyfin.** This is a read-only inspector.
- **Modern Plex GUIDs (`plex://`) require taggings/tags tables** with `tag_type=314`. If your DB is an older version, GUID resolution may be incomplete.
- **TV episode identity depends on parent_id relationships** in Plex. Episodes without parent season/show links will show limited metadata.
- **Custom artwork detection is best-effort.** Full artwork migration requires the Plex data directory, not just the DB.

## Output Example

```
$ switchkit inspect --plex-db com.plexapp.plugins.library.db
[INFO]  switchkit v0.1.0 — migration readiness inspector
[INFO]  Plex DB: com.plexapp.plugins.library.db (v140)
[INFO]  GUID formats: legacy: 5000, modern: 12000
[INFO]  Found 3 libraries: Movies (2,184), TV Shows (18,421 episodes), Music (3,809 tracks)
[INFO]  Found 2 regular Plex users: admin, sarah
[WARN]  Managed User:guest: standard Jellyfin account can be created instead
[INFO]  Watch states: 12,902 with external ID — 199 without external ID
[INFO]  Collections: 38 found
[INFO]  Inspect complete. 0 writes. Plex DB was read-only.
[INFO]  Report saved to migration-plan.json
[WARN]  This file contains viewing history — do not share unredacted.
```

## Privacy

- **No network calls.** This tool works fully offline.
- **Plex DB is opened read-only** (`mode=ro` via SQLite URI).
- **migration-plan.json contains viewing history** — usernames, titles, ratings, timestamps. Do not post unredacted.

## Requirements

- Python 3.10+
- A Plex database (`com.plexapp.plugins.library.db`)
- Plex Media Server 1.32+ (legacy GUIDs) or 1.20+ (modern GUIDs)

## License

AGPL-3.0. Source: https://github.com/switchkit/plex-to-jellyfin
