"""Plex SQLite database reader.

Reads com.plexapp.plugins.library.db (read-only) and extracts:
- Watch states (view_count, view_offset, last_viewed_at)
- Ratings (user star ratings)
- User accounts (local + external)
- Libraries (Movies, TV, Music)
- Collections
- Custom artwork references

Plex schema is reverse-engineered from community documentation.
Plex version support: 1.32+ (schema versions ~v1.38-v1.42).

Guid formats (legacy):
    imdb:   com.plexapp.agents.imdb://tt1234567?lang=en
    tmdb:   com.plexapp.agents.tmdb://12345?lang=en
    tvdb:   com.plexapp.agents.thetvdb://81189/1/1?lang=en
    local:  local://12345

Guid formats (modern Plex 1.20+):
    movie:    plex://movie/5d77682e3c3f8a001e9ad9b2
    show:     plex://show/5d9c0e8e7e8c1d001e9ae2c3
    episode:  plex://episode/5e2f1b3a8d7c2e001e9af4d5
    External IDs for modern GUIDs are in tags/taggings tables (tag_type=314).
"""

import sqlite3
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import re

logger = logging.getLogger(__name__)


@dataclass
class PlexUser:
    id: int
    name: str
    thumb: Optional[str] = None
    is_managed: bool = False
    is_external: bool = False


@dataclass
class PlexLibrary:
    id: int
    name: str
    section_type: str  # "movie", "show", "music", "photo", "other"
    item_count: int = 0


@dataclass
class WatchState:
    """A single watch state from Plex."""
    user_id: int
    user_name: str
    guid: str
    title: str
    year: Optional[int] = None
    media_type: str = "unknown"  # "movie", "episode", "track"
    view_count: int = 0
    view_offset: int = 0  # milliseconds
    last_viewed_at: Optional[int] = None  # Unix timestamp
    rating: Optional[float] = None  # 0.0-10.0 (Plex scale)
    skip_count: int = 0
    # Parsed external ID (for Jellyfin matching)
    guid_provider: Optional[str] = None  # "imdb", "tmdb", "tvdb", "local"
    guid_id: Optional[str] = None  # "tt1234567", "12345", etc.
    # TV episode identity (C2 fix)
    show_title: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    show_guid: Optional[str] = None  # GUID of the parent show
    # Diagnostics
    guid_format: Optional[str] = None  # "legacy", "modern", "local", "unknown"


@dataclass
class PlexCollection:
    id: int
    title: str
    smart: bool = False
    item_count: int = 0
    min_year: Optional[int] = None
    max_year: Optional[int] = None


@dataclass
class CustomArtwork:
    metadata_item_id: int
    file: str
    artwork_type: str


SECTION_TYPE_MAP = {
    1: "movie",
    2: "show",
    3: "show",   # season is part of show
    4: "show",   # episode is part of show
    8: "music",
    12: "photo",
    15: "other",  # DVR
}
MEDIA_TYPE_MAP = {1: "movie", 2: "show", 3: "season", 4: "episode", 8: "artist", 9: "album", 10: "track"}

# GUID parsing — legacy agents
LEGACY_GUID_PATTERN = re.compile(
    r'com\.plexapp\.agents\.(\w+)://([^?\s]+)'
)
# Modern Plex agents (Plex 1.20+)
MODERN_GUID_PATTERN = re.compile(
    r'plex://(movie|show|season|episode|track|album|artist)/([a-f0-9]+)'
)

# Normalize Plex agent names to standard provider keys
PROVIDER_NORMALIZE = {
    'thetvdb': 'tvdb',
    'themoviedb': 'tmdb',
    'imdb': 'imdb',
    'tmdb': 'tmdb',
    'tvdb': 'tvdb',
    'local': 'local',
}

# Tag type 314 = external provider IDs for modern agents
# Format: "imdb://tt1234567", "tmdb://12345", "tvdb://12345"
EXTERNAL_ID_TAG_TYPE = 314

# Tag type to provider mapping (from tag values)
EXTERNAL_TAG_PATTERN = re.compile(r'(imdb|tmdb|tvdb)://(.+)')


def parse_guid(guid: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse a Plex GUID into (provider, id, format).

    Returns (provider, id, format) where format is "legacy", "modern", "local", or None.

    >>> parse_guid('com.plexapp.agents.imdb://tt1234567?lang=en')
    ('imdb', 'tt1234567', 'legacy')

    >>> parse_guid('com.plexapp.agents.thetvdb://81189/1/1?lang=en')
    ('tvdb', '81189', 'legacy')

    >>> parse_guid('plex://movie/5d77682e3c3f8a001e9ad9b2')
    (None, None, 'modern')  # Needs DB lookup for external IDs

    >>> parse_guid('plex://episode/5e2f1b3a8d7c2e001e9af4d5')
    (None, None, 'modern')

    >>> parse_guid('local://12345')
    ('local', '12345', 'local')
    """
    # Legacy agents
    match = LEGACY_GUID_PATTERN.search(guid)
    if match:
        raw_provider = match.group(1).lower()
        provider = PROVIDER_NORMALIZE.get(raw_provider, raw_provider)
        return provider, match.group(2).split('/')[0], 'legacy'

    # Modern Plex agents (need DB lookup for external IDs)
    match = MODERN_GUID_PATTERN.search(guid)
    if match:
        return None, None, 'modern'

    # Local media
    if guid.startswith('local://'):
        return 'local', guid.replace('local://', ''), 'local'

    return None, None, None


def _parse_external_tag(tag: str) -> tuple[Optional[str], Optional[str]]:
    """Parse an external ID tag value into (provider, id).

    >>> _parse_external_tag('imdb://tt1234567')
    ('imdb', 'tt1234567')
    >>> _parse_external_tag('tmdb://12345')
    ('tmdb', '12345')
    """
    match = EXTERNAL_TAG_PATTERN.match(tag)
    if match:
        return match.group(1), match.group(2)
    return None, None


class PlexReader:
    """Read-only Plex database reader."""

    BATCH_SIZE = 2000  # Rows per fetchmany() batch (H9: streaming)

    def __init__(self, db_path: str):
        """Open the Plex database (read-only).

        Raises FileNotFoundError if db_path doesn't exist.
        Raises sqlite3.Error if the file is not a valid SQLite database.
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._tmp_dir: Optional[str] = None
        # Cache for external ID lookups (modern GUIDs)
        self._external_id_cache: dict[int, list[tuple[str, str]]] = {}

    @staticmethod
    def _fetch_batches(cursor: sqlite3.Cursor, batch_size: int = BATCH_SIZE):
        """Yield rows in batches to avoid loading everything into memory (H9 fix)."""
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield from rows

    def open(self) -> None:
        """Open the database connection (read-only).

        H-A fix: copies live WAL database to a temp location before opening,
        avoiding read failures on running Plex servers.
        """
        import tempfile
        import shutil

        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Plex database not found: {self.db_path}")

        db_path = Path(self.db_path).resolve()
        wal_path = Path(str(db_path) + '-wal')
        shm_path = Path(str(db_path) + '-shm')

        # If WAL files exist (Plex is likely running), copy to temp first
        if wal_path.exists():
            logger.info("Plex appears to be running (WAL files detected). "
                        "Copying database to temporary location for safe read...")
            tmp_dir = tempfile.mkdtemp(prefix='switchkit-')
            tmp_db = Path(tmp_dir) / db_path.name
            shutil.copy2(db_path, tmp_db)
            if wal_path.exists():
                shutil.copy2(wal_path, Path(tmp_dir) / wal_path.name)
            if shm_path.exists():
                shutil.copy2(shm_path, Path(tmp_dir) / shm_path.name)
            self._tmp_dir = tmp_dir
            db_path = tmp_db
        else:
            self._tmp_dir = None

        # Use pathlib for proper URI encoding
        db_uri = db_path.as_uri() + "?mode=ro"
        self.conn = sqlite3.connect(db_uri, uri=True)
        self.conn.row_factory = sqlite3.Row

        # Verify it's a Plex database (M4 fix: catch all sqlite3.Error)
        try:
            self.conn.execute("SELECT 1 FROM metadata_item_settings LIMIT 0")
        except sqlite3.Error:
            self.conn.close()
            self.conn = None
            self._cleanup_tmp()
            raise ValueError(
                f"Not a valid Plex database: {self.db_path}. "
                "Expected table 'metadata_item_settings' not found."
            )

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
        self._cleanup_tmp()

    def _cleanup_tmp(self) -> None:
        """Remove temporary database copy if one was created (H-A fix)."""
        if self._tmp_dir:
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def get_version(self) -> Optional[str]:
        """Get the Plex database schema version."""
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return str(row[0]) if row else None
        except sqlite3.Error:
            return "unknown"
    def _load_external_ids(self) -> None:
        """Preload all external IDs from tags/taggings (tag_type=314).

        Maps metadata_item_id -> [(provider, id), ...]
        Used for resolving modern plex:// GUIDs to external IDs.

        H9 fix: uses fetchmany() batches instead of fetchall().
        """
        if self._external_id_cache:
            return  # Already loaded

        try:
            cursor = self.conn.execute("""
                SELECT tg.metadata_item_id, t.tag
                FROM taggings tg
                JOIN tags t ON t.id = tg.tag_id
                WHERE t.tag_type = ?
            """, (EXTERNAL_ID_TAG_TYPE,))

            for row in self._fetch_batches(cursor):
                item_id = row['metadata_item_id']
                provider, ext_id = _parse_external_tag(row['tag'])
                if provider and ext_id:
                    if item_id not in self._external_id_cache:
                        self._external_id_cache[item_id] = []
                    self._external_id_cache[item_id].append((provider, ext_id))
        except sqlite3.OperationalError:
            logger.debug("External ID tags table not found — modern GUIDs will be unresolved")

    def _resolve_external_id(self, metadata_item_id: int) -> tuple[Optional[str], Optional[str]]:
        """Resolve external IDs for a metadata item (modern GUIDs).

        Returns (provider, id) from tags table, or (None, None).
        Prefer TMDb, then IMDb, then TVDb.
        """
        self._load_external_ids()
        entries = self._external_id_cache.get(metadata_item_id, [])
        if not entries:
            return None, None

        # Prefer TMDb > IMDb > TVDb
        by_provider = {p: eid for p, eid in entries}
        for preferred in ('tmdb', 'imdb', 'tvdb'):
            if preferred in by_provider:
                return preferred, by_provider[preferred]
        return entries[0]  # fallback: return first available

    def get_guid_format_distribution(self) -> dict[str, int]:
        """Get distribution of GUID formats across metadata_items.

        Returns counts like {'legacy': 5000, 'modern': 12000, 'local': 50, 'unknown': 3}
        Useful for diagnostics — shows how many items need modern GUID resolution.
        """
        dist: dict[str, int] = {}
        rows = self.conn.execute(
            "SELECT guid FROM metadata_items WHERE guid IS NOT NULL"
        ).fetchall()
        for row in rows:
            _, _, fmt = parse_guid(row['guid'])
            fmt = fmt or 'unknown'
            dist[fmt] = dist.get(fmt, 0) + 1
        return dist

    def get_users(self) -> list[PlexUser]:
        """Get all Plex user accounts (local)."""
        # Real Plex accounts table may or may not have 'thumb' column.
        # Query columns that definitely exist: id, name.
        try:
            rows = self.conn.execute(
                "SELECT id, name FROM accounts ORDER BY id"
            ).fetchall()
        except sqlite3.Error as e:
            logger.warning("Cannot read accounts table: %s", e)
            return []

        users = []
        for row in rows:
            is_managed = (row['name'] or '').startswith('Managed User:') or \
                         row['name'] == 'Guest'
            users.append(PlexUser(
                id=row['id'],
                name=row['name'] or 'Unknown',
                thumb=None,
                is_managed=is_managed,
                is_external=False,
            ))
        return users

    def get_libraries(self) -> list[PlexLibrary]:
        """Get all library sections with item counts.

        Fixed C1/H2: counts all media types per library using conditional aggregation
        instead of filtering with WHERE, so music/photo libraries aren't dropped.
        """
        rows = self.conn.execute("""
            SELECT
                ls.id, ls.name, ls.section_type,
                COUNT(mi.id) as item_count
            FROM library_sections ls
            LEFT JOIN metadata_items mi
                ON mi.library_section_id = ls.id
                AND mi.metadata_type IN (1, 4, 8, 10)  -- movie, episode, track, album
            GROUP BY ls.id
            ORDER BY ls.id
        """).fetchall()

        libraries = []
        for row in rows:
            section_type = SECTION_TYPE_MAP.get(
                row['section_type'], f"unknown({row['section_type']})"
            )
            libraries.append(PlexLibrary(
                id=row['id'],
                name=row['name'],
                section_type=section_type,
                item_count=row['item_count'] or 0,
            ))
        return libraries

    def get_watch_states(self) -> list[WatchState]:
        """Get all watch states with user and media info.

        C1 fix: resolves modern plex:// GUIDs via external ID tags.
        C2 fix: preserves TV episode identity (season/episode numbers, show title).
        M1 fix: uses LEFT JOIN for accounts to include external/shared users.
        """
        # Preload external IDs for modern GUID resolution
        self._load_external_ids()

        cursor = self.conn.execute("""
            SELECT
                mis.account_id,
                COALESCE(a.name, 'External User ' || mis.account_id) as user_name,
                mis.guid,
                mi.id as metadata_item_id,
                mi.title,
                mi.year,
                mi.metadata_type,
                mi."index" as item_index,
                mis.view_count,
                mis.view_offset,
                mis.last_viewed_at,
                mis.rating,
                mis.skip_count,
                -- Parent (season) info for episodes
                parent."index" as season_number,
                parent.title as season_title,
                -- Grandparent (show) info for episodes
                grandparent.title as show_title,
                grandparent.guid as show_guid,
                grandparent.id as grandparent_item_id
            FROM metadata_item_settings mis
            -- H-B fix: deduplicate on GUID — pick one canonical metadata_item per GUID
            -- to prevent watch state fan-out when same media exists in multiple libraries
            JOIN (
                SELECT guid, MIN(id) as canonical_id
                FROM metadata_items
                GROUP BY guid
            ) mi_canon ON mi_canon.guid = mis.guid
            JOIN metadata_items mi ON mi.id = mi_canon.canonical_id
            LEFT JOIN accounts a ON a.id = mis.account_id
            LEFT JOIN metadata_items parent
                ON parent.id = mi.parent_id AND mi.metadata_type = 4
            LEFT JOIN metadata_items grandparent
                ON grandparent.id = parent.parent_id AND mi.metadata_type = 4
            WHERE (mis.view_count > 0 OR mis.view_offset > 0 OR mis.rating IS NOT NULL)
            ORDER BY a.id, mi.title
        """)

        watch_states = []
        for row in self._fetch_batches(cursor):
            guid = row['guid']
            provider, guid_id, fmt = parse_guid(guid)

            # For modern GUIDs, resolve external IDs from tags table (C1 fix)
            # TV episodes: external IDs are on the grandparent show, not the episode
            meta_type = row['metadata_type']
            if fmt == 'modern':
                if meta_type == 4 and row['grandparent_item_id']:  # episode
                    provider, guid_id = self._resolve_external_id(row['grandparent_item_id'])
                elif row['metadata_item_id']:
                    provider, guid_id = self._resolve_external_id(row['metadata_item_id'])

            # For TV episodes, use episode index from the row (C2 fix)
            media_type = MEDIA_TYPE_MAP.get(row['metadata_type'], 'unknown')
            season_num = row['season_number']
            episode_num = row['item_index'] if media_type == 'episode' else None
            show_title = row['show_title']
            show_guid = row['show_guid']

            ws = WatchState(
                user_id=row['account_id'],
                user_name=row['user_name'],
                guid=guid,
                title=row['title'],
                year=row['year'],
                media_type=media_type,
                view_count=row['view_count'] or 0,
                view_offset=row['view_offset'] or 0,
                last_viewed_at=row['last_viewed_at'],
                rating=row['rating'],
                skip_count=row['skip_count'] or 0,
                guid_provider=provider,
                guid_id=guid_id,
                show_title=show_title,
                season_number=season_num,
                episode_number=episode_num,
                show_guid=show_guid,
                guid_format=fmt,
            )
            watch_states.append(ws)
        return watch_states

    def get_collections(self) -> list[PlexCollection]:
        """Get all collections (C-A fix: real Plex schema).

        Real Plex stores collections as metadata_items with metadata_type=18.
        Note: smart/manual distinction not available as a column in real Plex.
        """
        try:
            rows = self.conn.execute("""
                SELECT
                    id, title, 0 as is_smart,
                    (SELECT COUNT(*) FROM taggings tg
                     WHERE tg.tag_id IN (
                         SELECT t.id FROM tags t
                         WHERE t.tag_type = 19 AND t.tag = mi.guid
                     )) as item_count
                FROM metadata_items mi
                WHERE metadata_type = 18
                ORDER BY title
            """).fetchall()

            return [
                PlexCollection(
                    id=row['id'],
                    title=row['title'],
                    smart=bool(row['is_smart']),
                    item_count=row['item_count'] or 0,
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.warning("Collections schema not found (%s). "
                           "Collections data unavailable.", e)
            return []

    def get_custom_artwork(self) -> list[CustomArtwork]:
        """Get custom artwork references (C-B fix: real Plex column names).

        Real Plex uses user_thumb_url, user_art_url, user_banner_url, user_music_url.
        The _url suffix was missing in earlier versions built against fabricated fixture.
        """
        try:
            rows = self.conn.execute("""
                SELECT id as metadata_item_id,
                       user_thumb_url as file,
                       'poster' as artwork_type
                FROM metadata_items
                WHERE user_thumb_url LIKE 'upload://%'
                UNION ALL
                SELECT id as metadata_item_id,
                       user_art_url as file,
                       'background' as artwork_type
                FROM metadata_items
                WHERE user_art_url LIKE 'upload://%'
            """).fetchall()

            return [
                CustomArtwork(
                    metadata_item_id=row['metadata_item_id'],
                    file=row['file'],
                    artwork_type=row['artwork_type'],
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.warning("Artwork columns not found (%s). "
                           "Custom artwork data unavailable.", e)
            return []

    def get_diagnostics(self) -> dict:
        """Get diagnostic information about the Plex database.

        Useful for understanding GUID format distribution, join quality,
        and potential issues before migration.
        """
        # GUID format distribution
        guid_dist = self.get_guid_format_distribution()

        # Watch state join diagnostics (M12 fix)
        total_settings = self.conn.execute(
            "SELECT COUNT(*) FROM metadata_item_settings"
        ).fetchone()[0]

        migratable_settings = self.conn.execute(
            """SELECT COUNT(*) FROM metadata_item_settings
               WHERE view_count > 0 OR view_offset > 0 OR rating IS NOT NULL"""
        ).fetchone()[0]

        # Check how many settings rows have matching metadata_items (deduped per H-B)
        joined = self.conn.execute(
            """SELECT COUNT(*) FROM metadata_item_settings mis
               JOIN (
                   SELECT guid, MIN(id) as canonical_id
                   FROM metadata_items GROUP BY guid
               ) mi_canon ON mi_canon.guid = mis.guid
               WHERE mis.view_count > 0 OR mis.view_offset > 0 OR mis.rating IS NOT NULL"""
        ).fetchone()[0]

        unjoined = max(0, migratable_settings - joined)  # never negative

        # Check for duplicate GUIDs in metadata_items (real library dupes, not multi-user)
        dupes = self.conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT guid, COUNT(*) as cnt
                   FROM metadata_items
                   WHERE guid IS NOT NULL
                   GROUP BY guid HAVING cnt > 1
               )"""
        ).fetchone()[0]

        return {
            'schema_version': self.get_version(),
            'guid_format_distribution': guid_dist,
            'total_settings_rows': total_settings,
            'migratable_settings_rows': migratable_settings,
            'joined_watch_states': joined,
            'unjoined_watch_states': unjoined,
            'duplicate_guids': dupes,
        }

    def get_collection_memberships(self) -> list[dict]:
        """Get all collection item memberships (C-A fix: real Plex schema).

        Collections are metadata_items with metadata_type=18.
        Membership is via taggings: a tagging links a media item to a
        tag whose tag_type=19 and tag value is the collection's GUID.
        """
        try:
            cursor = self.conn.execute("""
                SELECT
                    coll.id as collection_id,
                    coll.title as collection_title,
                    mi.id as metadata_item_id,
                    mi.metadata_type,
                    mi.title as item_title,
                    mi.guid as item_guid
                FROM metadata_items coll
                JOIN tags t ON t.tag_type = 19 AND t.tag = coll.guid
                JOIN taggings tg ON tg.tag_id = t.id
                JOIN metadata_items mi ON mi.id = tg.metadata_item_id
                WHERE coll.metadata_type = 18
                ORDER BY coll.title, mi.title
            """)

            memberships = []
            for row in self._fetch_batches(cursor):
                guid = row['item_guid']
                _, _, fmt = parse_guid(guid)

                ext_provider = None
                ext_id = None

                if fmt == 'modern' and row['metadata_item_id']:
                    ext_provider, ext_id = self._resolve_external_id(row['metadata_item_id'])
                elif fmt == 'legacy':
                    ext_provider, ext_id, _ = parse_guid(guid)

                memberships.append({
                    'collection_id': row['collection_id'],
                    'collection_title': row['collection_title'],
                    'metadata_item_id': row['metadata_item_id'],
                    'item_title': row['item_title'],
                    'item_guid': guid,
                    'external_id_provider': ext_provider,
                    'external_id': ext_id,
                })
            return memberships
        except sqlite3.Error as e:
            logger.warning("Collection membership schema not found (%s). "
                           "Collection membership data unavailable.", e)
            return []

    def get_all_stats(self) -> dict:
        """Get a complete snapshot of the Plex database for dry-run output.

        C1 fix: includes diagnostics for GUID format distribution.
        C2 fix: watch states now carry TV episode identity.
        H4/H5 fix: renamed matched/unmatched to external ID present/absent.
        H1 fix: artwork queries real Plex user_thumb/user_art columns.
        M6/M18 fix: includes artwork list and collection memberships.
        """
        users = self.get_users()
        libraries = self.get_libraries()
        watch_states = self.get_watch_states()
        collections = self.get_collections()
        artwork = self.get_custom_artwork()
        collection_memberships = self.get_collection_memberships()
        diagnostics = self.get_diagnostics()

        # Count watch states by external ID status (H4 fix: clearer naming)
        with_external_id = [
            w for w in watch_states
            if w.guid_provider in ('imdb', 'tmdb', 'tvdb')
        ]
        without_external_id = [
            w for w in watch_states
            if w.guid_provider not in ('imdb', 'tmdb', 'tvdb')
        ]

        return {
            'version': self.get_version(),
            'users': [asdict(u) for u in users],
            'managed_users': [asdict(u) for u in users if u.is_managed],
            'libraries': [asdict(lib) for lib in libraries],
            'collection_count': len(collections),
            'collections': [asdict(c) for c in collections],
            'collection_memberships': collection_memberships,
            'watch_state_count': len(watch_states),
            'watch_states_external_id_present': len(with_external_id),
            'watch_states_external_id_missing': len(without_external_id),
            'watch_states': [asdict(w) for w in watch_states],
            'custom_artwork_count': len(artwork),
            'custom_artwork': [asdict(a) for a in artwork],
            'diagnostics': diagnostics,
        }
