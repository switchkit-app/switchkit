"""Generate a minimal Plex test database fixture for testing.

Creates a com.plexapp.plugins.library.db with:
- 3 users (admin, sarah, guest managed user)
- 2 libraries (Movies, TV Shows)
- Legacy GUID movies + modern plex:// GUID movies
- TV episodes with parent_id (season/show hierarchy)
- External ID tags (taggings/tags with tag_type=314)
- 3 collections
"""

import sqlite3
import os

FIXTURE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(FIXTURE_DIR, "plex-test.db")


def create_test_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")

    # Schema version
    db.execute("CREATE TABLE schema_version (schema_version INTEGER)")
    db.execute("INSERT INTO schema_version VALUES (140)")

    # Migrations
    db.execute("CREATE TABLE migrations (version INTEGER)")
    db.execute("INSERT INTO migrations VALUES (140)")

    # Accounts
    db.execute("""
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            thumb TEXT,
            hashed_password TEXT
        )
    """)
    db.executemany(
        "INSERT INTO accounts VALUES (?, ?, ?, ?)",
        [
            (1, "admin", "/thumb/admin.png", None),
            (2, "sarah", "/thumb/sarah.png", None),
            (3, "Managed User:guest", None, None),
        ],
    )

    # Library sections
    db.execute("""
        CREATE TABLE library_sections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            section_type INTEGER NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.executemany(
        "INSERT INTO library_sections VALUES (?, ?, ?, ?)",
        [
            (1, "Movies", 1, 1710000000),
            (2, "TV Shows", 2, 1710000000),
            (3, "Music", 8, 1710000000),  # Music library (tests C1/H2 fix)
        ],
    )

    # Metadata items — includes parent_id for episode hierarchy
    db.execute("""
        CREATE TABLE metadata_items (
            id INTEGER PRIMARY KEY,
            library_section_id INTEGER NOT NULL,
            metadata_type INTEGER NOT NULL,
            parent_id INTEGER,
            title TEXT NOT NULL,
            title_sort TEXT,
            original_title TEXT,
            year INTEGER,
            duration INTEGER,
            added_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            guid TEXT NOT NULL UNIQUE,
            media_item_count INTEGER DEFAULT 0,
            "index" INTEGER,
            user_thumb TEXT,
            user_art TEXT
        )
    """)

    # Tags and taggings — for modern GUID external ID resolution
    db.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            tag TEXT NOT NULL,
            tag_type INTEGER NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE taggings (
            id INTEGER PRIMARY KEY,
            metadata_item_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL
        )
    """)

    # Collections
    db.execute("""
        CREATE TABLE collections (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            smart INTEGER NOT NULL DEFAULT 0,
            min_year INTEGER,
            max_year INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE collection_items (
            id INTEGER PRIMARY KEY,
            collection_id INTEGER NOT NULL,
            metadata_item_id INTEGER NOT NULL
        )
    """)

    # Media parts (for custom artwork detection)
    db.execute("""
        CREATE TABLE media_parts (
            id INTEGER PRIMARY KEY,
            media_item_id INTEGER,
            metadata_item_id INTEGER NOT NULL,
            file TEXT NOT NULL,
            size INTEGER DEFAULT 0
        )
    """)

    # Metadata item settings (watch states, ratings)
    db.execute("""
        CREATE TABLE metadata_item_settings (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL,
            guid TEXT NOT NULL,
            rating REAL,
            view_count INTEGER DEFAULT 0,
            last_viewed_at INTEGER,
            view_offset INTEGER DEFAULT 0,
            skip_count INTEGER DEFAULT 0,
            last_skipped_at INTEGER
        )
    """)

    # --- Insert data ---

    # Legacy GUID movies
    legacy_movies = [
        (1, 1, None, "The Matrix", "Matrix", "The Matrix", 1999, 8160000,
         "com.plexapp.agents.imdb://tt0133093?lang=en"),
        (2, 1, None, "Inception", "Inception", "Inception", 2010, 8880000,
         "com.plexapp.agents.imdb://tt1375666?lang=en"),
        (3, 1, None, "Interstellar", "Interstellar", "Interstellar", 2014, 10140000,
         "com.plexapp.agents.imdb://tt0816692?lang=en"),
        (4, 1, None, "The Dark Knight", "Dark Knight", "The Dark Knight", 2008, 9120000,
         "com.plexapp.agents.imdb://tt0468569?lang=en"),
        (5, 1, None, "Pulp Fiction", "Pulp Fiction", "Pulp Fiction", 1994, 9240000,
         "com.plexapp.agents.tmdb://680?lang=en"),
        (6, 1, None, "Fight Club", "Fight Club", "Fight Club", 1999, 8340000,
         "com.plexapp.agents.tmdb://550?lang=en"),
        (7, 1, None, "Forrest Gump", "Forrest Gump", "Forrest Gump", 1994, 8520000,
         "com.plexapp.agents.imdb://tt0109830?lang=en"),
        (8, 1, None, "The Shawshank Redemption", "Shawshank Redemption", None, 1994, 8520000,
         "com.plexapp.agents.imdb://tt0111161?lang=en"),
        (9, 1, None, "Gladiator", "Gladiator", None, 2000, 9300000,
         "com.plexapp.agents.tmdb://98?lang=en"),
        (10, 1, None, "Local File Movie", "Local File Movie", None, None, 6000000,
         "local://1001"),
        (11, 1, None, "No ID Movie", "No ID Movie", None, 2023, 7200000,
         "com.plexapp.agents.none://abc123"),
    ]

    # Modern plex:// GUID movies (Plex 1.20+)
    modern_movies = [
        (20, 1, None, "Dune", "Dune", "Dune", 2021, 9300000,
         "plex://movie/5d77682e3c3f8a001e9ad9b1"),
        (21, 1, None, "Everything Everywhere", "Everything Everywhere", None, 2022, 8340000,
         "plex://movie/5d77682e3c3f8a001e9ad9b2"),
        (22, 1, None, "Oppenheimer", "Oppenheimer", "Oppenheimer", 2023, 10860000,
         "plex://movie/5d77682e3c3f8a001e9ad9b3"),
    ]

    all_movies = legacy_movies + modern_movies
    for item in all_movies:
        db.execute(
            """INSERT INTO metadata_items
               (id, library_section_id, metadata_type, parent_id, title, title_sort,
                original_title, year, duration, guid)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            item,
        )

    # External ID tags for modern GUID movies (tag_type=314)
    modern_tags = [
        # Dune -> tmdb://438631
        (20, 'tmdb://438631'),
        # Everything Everywhere -> imdb://tt6710474
        (21, 'imdb://tt6710474'),
        (21, 'tmdb://545611'),  # also has TMDB
        # Oppenheimer -> tmdb://872585
        (22, 'tmdb://872585'),
    ]
    tag_id = 1
    for item_id, tag_val in modern_tags:
        db.execute("INSERT INTO tags (id, tag, tag_type) VALUES (?, ?, 314)", (tag_id, tag_val))
        db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))
        tag_id += 1

    # TV Show hierarchy: Show -> Seasons -> Episodes
    # Breaking Bad (show) — id 100
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (100, 2, 2, NULL, 'Breaking Bad', 2008,
           'com.plexapp.agents.thetvdb://81189?lang=en', NULL)"""
    )
    # Breaking Bad Season 1 — id 101
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (101, 2, 3, 100, 'Season 1', 2008,
           'com.plexapp.agents.thetvdb://81189/1?lang=en', 1)"""
    )
    # Breaking Bad S01E01 — id 102
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (102, 2, 4, 101, 'Pilot', 2008,
           'com.plexapp.agents.thetvdb://81189/1/1?lang=en', 3480000, 1)"""
    )
    # Breaking Bad S01E02 — id 103
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (103, 2, 4, 101, 'Cat''s in the Bag', 2008,
           'com.plexapp.agents.thetvdb://81189/1/2?lang=en', 2880000, 2)"""
    )

    # Stranger Things (show) — id 110
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (110, 2, 2, NULL, 'Stranger Things', 2016,
           'plex://show/5d9c0e8e7e8c1d001e9ae2c1', NULL)"""
    )
    # Stranger Things Season 1 — id 111
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (111, 2, 3, 110, 'Season 1', 2016,
           'plex://season/5d9c0e8e7e8c1d001e9ae2c2', 1)"""
    )
    # Stranger Things S01E01 — id 112
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (112, 2, 4, 111, 'Chapter One', 2016,
           'plex://episode/5d9c0e8e7e8c1d001e9ae2c3', 2880000, 1)"""
    )
    # Stranger Things S01E02 — id 113
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (113, 2, 4, 111, 'Chapter Two', 2016,
           'plex://episode/5d9c0e8e7e8c1d001e9ae2c4', 3360000, 2)"""
    )

    # External ID tags for Stranger Things (modern GUIDs)
    # Real Plex only stores external IDs on the show (type 2), never on episodes
    db.execute("INSERT INTO tags (id, tag, tag_type) VALUES (?, ?, 314)", (tag_id, 'tvdb://305288'))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (110, ?)", (tag_id,))
    tag_id += 1
    # NO episode-level external ID tags — these don't exist in real Plex databases

    # A few more episodes (The Office, local, extra)
    episodes = [
        (120, 2, None, "The Office - Pilot", 2005, 1380000,
         "com.plexapp.agents.thetvdb://73244/1/1?lang=en", 1),
        (121, 2, None, "Local Episode", None, 1800000, "local://2001", 1),
    ]
    for item in episodes:
        db.execute(
            """INSERT INTO metadata_items
               (id, library_section_id, metadata_type, parent_id, title, year, duration, guid, "index")
               VALUES (?, ?, 4, ?, ?, ?, ?, ?, ?)""",
            item,
        )

    # Music track (tests C1/H2 fix)
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid)
           VALUES (200, 3, 10, NULL, 'Random Album', 2023,
           'com.plexapp.agents.tmdb://9999?lang=en')"""
    )

    # --- Watch states ---
    watch_states = [
        # admin: watched The Matrix
        (1, "com.plexapp.agents.imdb://tt0133093?lang=en", 8.0, 3, 1715000000, 0, 0),
        # admin: halfway through Inception
        (1, "com.plexapp.agents.imdb://tt1375666?lang=en", None, 1, 1715000000, 4440000, 0),
        # admin: watched Interstellar, rated 9
        (1, "com.plexapp.agents.imdb://tt0816692?lang=en", 9.0, 2, 1715000000, 0, 0),
        # admin: local file movie (unmatched)
        (1, "local://1001", 7.0, 1, 1715000000, 0, 0),
        # admin: Breaking Bad S01E01
        (1, "com.plexapp.agents.thetvdb://81189/1/1?lang=en", None, 1, 1715000000, 0, 0),
        # admin: Breaking Bad S01E02
        (1, "com.plexapp.agents.thetvdb://81189/1/2?lang=en", None, 1, 1715000000, 600000, 0),
        # admin: Dune (modern GUID)
        (1, "plex://movie/5d77682e3c3f8a001e9ad9b1", 9.0, 2, 1715000000, 0, 0),
        # sarah: watched The Matrix
        (2, "com.plexapp.agents.imdb://tt0133093?lang=en", 9.5, 5, 1715000000, 0, 0),
        # sarah: watched Fight Club
        (2, "com.plexapp.agents.tmdb://550?lang=en", 8.0, 2, 1715000000, 0, 0),
        # sarah: Stranger Things S01E01 (modern GUID)
        (2, "plex://episode/5d9c0e8e7e8c1d001e9ae2c3", None, 1, 1715000000, 0, 0),
        # sarah: no ID movie (unmatched)
        (2, "com.plexapp.agents.none://abc123", 5.0, 1, 1715000000, 300000, 0),
        # guest: watched The Matrix (managed user)
        (3, "com.plexapp.agents.imdb://tt0133093?lang=en", None, 1, 1715000000, 0, 0),
        # external user (id=99, not in accounts table — tests M1 fix)
        (99, "com.plexapp.agents.imdb://tt0133093?lang=en", None, 2, 1715000000, 0, 0),
    ]

    for ws in watch_states:
        db.execute(
            """INSERT INTO metadata_item_settings
               (account_id, guid, rating, view_count, last_viewed_at, view_offset, skip_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ws,
        )

    # --- Collections ---
    db.execute("INSERT INTO collections VALUES (1, 'Sci-Fi Favorites', 0, 1999, 2014)")
    db.execute("INSERT INTO collections VALUES (2, 'Best of the 90s', 0, 1994, 1999)")
    db.execute("INSERT INTO collections VALUES (3, '4K Collection', 1, NULL, NULL)")

    db.executemany(
        "INSERT INTO collection_items (collection_id, metadata_item_id) VALUES (?, ?)",
        [(1, 1), (1, 2), (1, 3), (1, 4), (1, 20), (2, 1), (2, 5), (2, 6), (2, 7), (2, 8)],
    )

    # Custom artwork — use real Plex schema (H1 fix: user_thumb/user_art, not media_parts)
    # Add user_thumb and user_art columns to metadata_items (already created above)
    # Update a few items with upload:// artwork references
    db.execute("UPDATE metadata_items SET user_thumb = 'upload://posters/the_matrix_custom' WHERE id = 1")
    db.execute("UPDATE metadata_items SET user_art = 'upload://backgrounds/interstellar_bg' WHERE id = 3")
    db.execute("UPDATE metadata_items SET user_thumb = 'upload://posters/inception_alt' WHERE id = 2")

    db.commit()
    db.close()
    print(f"Test fixture created: {DB_PATH}")


if __name__ == "__main__":
    create_test_db()
