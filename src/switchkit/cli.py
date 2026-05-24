"""Switch Kit CLI: Plex → Jellyfin migration readiness inspector.

Usage:
    switchkit inspect --plex-db /path/to/plex/db
    switchkit inspect --plex-db /path/to/plex/db --output plan.json
"""

import json
import sys
import logging
import os
from pathlib import Path

import click

from .plex_reader import PlexReader
from . import __version__

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)-5s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("switchkit")

# Color helpers — honor NO_COLOR
INFO = "[INFO]"
WARN = "[WARN]"
ERR = "[ERROR]"


def _use_color() -> bool:
    """Check if color output should be used."""
    return os.environ.get('NO_COLOR', '').lower() not in ('1', 'true', 'yes')


def _info(msg: str) -> None:
    if _use_color():
        click.echo(f"\033[32m{INFO}\033[0m  {msg}", err=True)
    else:
        click.echo(f"{INFO}  {msg}", err=True)


def _warn(msg: str) -> None:
    if _use_color():
        click.echo(f"\033[33m{WARN}\033[0m  {msg}", err=True)
    else:
        click.echo(f"{WARN}  {msg}", err=True)


def _error(msg: str) -> None:
    if _use_color():
        click.echo(f"\033[31m{ERR}\033[0m  {msg}", err=True)
    else:
        click.echo(f"{ERR}  {msg}", err=True)


def _validate_output_path(path_str: str) -> str:
    """Validate and normalize output path (C6 fix: prevent directory traversal).

    Raises click.BadParameter if path is unsafe.

    Blocks: ../../../etc/passwd (relative) and /foo/../../../etc/passwd (absolute).
    Allows: /tmp/plan.json, ./plan.json, plan.json, /absolute/output/path.json.
    Requires .json extension.
    """
    # Reject paths containing '..' segments BEFORE resolution
    # This catches both relative (../../../) and absolute (/foo/../../../) attempts
    if '..' in Path(path_str).parts:
        raise click.BadParameter(
            f"Output path may not contain '..' traversal. Got: {path_str}"
        )

    resolved = Path(path_str).resolve()

    # Require .json extension
    if not resolved.suffix == '.json':
        raise click.BadParameter(
            f"Output file must have .json extension. Got: {path_str}"
        )

    return str(resolved)


@click.group()
@click.version_option(__version__, prog_name="switchkit")
def main():
    """Switch Kit — Plex→Jellyfin migration readiness inspector.

    Opens your Plex database read-only and exports what would transfer.
    No writes. No network. No account required.

    \b
    Examples:
      switchkit inspect --plex-db com.plexapp.plugins.library.db
      switchkit inspect --plex-db com.plexapp.plugins.library.db --output plan.json
    """
    pass


@main.command()
@click.option(
    "--plex-db", required=True,
    help="Path to Plex database (com.plexapp.plugins.library.db).",
)
@click.option(
    "--output", "-o", default=None,
    help="Path for the migration plan JSON. Default: migration-plan.json.",
)
def inspect(plex_db, output):
    """Inspect a Plex database and export migration readiness report.

    Opens the Plex SQLite database read-only. No network calls. No writes.

    \b
    Extracts:
      - Library inventory (Movies, TV, Music)
      - User accounts (local + external)
      - Watch states and ratings
      - Resume positions
      - Collections
      - GUID format diagnostics (legacy vs modern agents)

    Output: migration-plan.json (do not share unredacted — contains viewing history).
    """
    if not os.path.exists(plex_db):
        _error(f"Plex database not found: {plex_db}")
        sys.exit(1)

    if not os.path.isfile(plex_db):
        _error(f"Path is not a file: {plex_db}")
        sys.exit(1)

    if not os.access(plex_db, os.R_OK):
        _error(f"File not readable: {plex_db}")
        sys.exit(1)

    _info(f"switchkit v{__version__} — migration readiness inspector")

    # Validate output path (C6 fix)
    output_path = output or "migration-plan.json"
    try:
        output_path = _validate_output_path(output_path)
    except click.BadParameter as e:
        _error(str(e))
        sys.exit(1)

    # --- Read Plex ---
    try:
        reader = PlexReader(plex_db)
        reader.open()
    except FileNotFoundError as e:
        _error(str(e))
        sys.exit(1)
    except ValueError as e:
        _error(str(e))
        sys.exit(1)
    except Exception as e:
        _error(f"Failed to open Plex database: {e}")
        sys.exit(1)

    try:
        _info(f"Plex DB: {plex_db} (v{reader.get_version()})")

        # M20 fix: single get_all_stats() call — use dict for both display and output
        plan = reader.get_all_stats()
        plan['generated_by'] = f"switchkit v{__version__}"
        plan['mode'] = "inspect"
        plan['_WARNING'] = (
            "This file contains viewing history, usernames, ratings, and file paths. "
            "Do not share unredacted. Use --output with caution. "
            "Consider redacting user names and titles before posting to public forums."
        )

        # --- Print summary from plan dict (no duplicate DB reads) ---
        diag = plan.get('diagnostics', {})
        guid_dist = diag.get('guid_format_distribution', {})
        if guid_dist:
            dist_str = ", ".join(f"{k}: {v}" for k, v in sorted(guid_dist.items()))
            _info(f"GUID formats: {dist_str}")
        if diag.get('unjoined_watch_states', 0) > 0:
            _warn(f"{diag['unjoined_watch_states']} watch state rows could not be joined to media items")

        # Libraries
        libraries = plan.get('libraries', [])
        if libraries:
            lib_strs = []
            for lib in libraries:
                suffix = ""
                if lib['section_type'] == "show":
                    suffix = "episodes"
                elif lib['section_type'] == "music":
                    suffix = "items"
                lib_strs.append(
                    f"{lib['name']} ({lib['item_count']:,} {suffix})" if suffix
                    else f"{lib['name']} ({lib['item_count']:,})"
                )
            _info(f"Found {len(libraries)} libraries: {', '.join(lib_strs)}")

        # Users
        users = plan.get('users', [])
        managed = [u for u in users if u.get('is_managed')]
        regular = [u for u in users if not u.get('is_managed')]
        _info(f"Found {len(regular)} regular Plex users: {', '.join(u['name'] for u in regular)}")
        for m in managed:
            _warn(f"{m['name']}: Plex managed user — standard Jellyfin accounts can be created instead")

        # Watch states
        _info(f"Watch states: {plan['watch_states_external_id_present']:,} with external ID — "
              f"{plan['watch_states_external_id_missing']:,} without external ID")

        # Collections
        _info(f"Collections: {plan['collection_count']:,} found")

        # Custom artwork
        artwork_count = plan.get('custom_artwork_count', 0)
        if artwork_count:
            _info(f"Custom artwork references: {artwork_count:,} found (poster/art/background files)")
        else:
            _info("Custom artwork: no local poster/art files detected")

        # --- Write plan ---
        with open(output_path, 'w') as f:
            json.dump(plan, f, indent=2, default=str)

        _info("Inspect complete. Plex DB was read-only (temp copy created if WAL detected).")
        _info(f"Report saved to {output_path}")
        _warn("This file contains viewing history — do not share unredacted.")

    finally:
        reader.close()


# Removed migrate, rollback, --execute, --dry-run commands.
# These will be re-added when write mode is actually implemented (v0.3.0+).
# See audit findings C4 and H7.


if __name__ == "__main__":
    main()
