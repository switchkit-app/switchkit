"""Generate a Plex test database fixture matching REAL Plex schema.

Creates a com.plexapp.plugins.library.db with schema derived from
actual Plex Media Server exports, not hand-crafted assumptions.

Key differences from previous fabricated fixture (C-A/C-B fixes):
- Collections: metadata_items with metadata_type=18 + taggings (tag_type=2)
- Artwork: user_thumb_url / user_art_url columns (not user_thumb / user_art)
- No fictional 'collections'/'collection_items' tables
- GUIDs are NOT UNIQUE (real Plex allows same GUID in multiple libraries)
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

    # Schema migrations (real Plex uses schema_migrations, not schema_version)
    db.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO schema_migrations VALUES (140)")

    # Accounts — local Plex users
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
            (3, "Music", 8, 1710000000),
        ],
    )

    # Metadata items — real Plex schema
    # GUID is NOT UNIQUE (same movie can be in multiple libraries)
    # user_thumb_url / user_art_url are the real column names
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
            guid TEXT NOT NULL,
            media_item_count INTEGER DEFAULT 0,
            "index" INTEGER,
            user_thumb_url TEXT,
            user_art_url TEXT,
            user_banner_url TEXT,
            user_music_url TEXT
        )
    """)

    # Tags — real Plex schema (includes metadata_item_id for scoping)
    db.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            metadata_item_id INTEGER,
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

    # Media parts (for playable files)
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

    # Modern plex:// GUID movies
    modern_movies = [
        (20, 1, None, "Dune", "Dune", "Dune", 2021, 9300000,
         "plex://movie/5d77682e3c3f8a001e9ad9b1"),
        (21, 1, None, "Everything Everywhere", "Everything Everywhere", None, 2022, 8340000,
         "plex://movie/5d77682e3c3f8a001e9ad9b2"),
        (22, 1, None, "Oppenheimer", "Oppenheimer", "Oppenheimer", 2023, 10860000,
         "plex://movie/5d77682e3c3f8a001e9ad9b3"),
    ]

    # Duplicate GUID movie (tests H-B: same GUID, different libraries)
    dup_movie = (23, 1, None, "The Matrix (4K)", "Matrix (4K)", "The Matrix", 1999, 8160000,
         "com.plexapp.agents.imdb://tt0133093?lang=en")

    all_movies = legacy_movies + modern_movies + [dup_movie]
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
        (20, 'tmdb://438631'),
        (21, 'tmdb://545611'),
        (22, 'tmdb://872585'),
    ]
    tag_id = 1
    for item_id, tag_val in modern_tags:
        db.execute("INSERT INTO tags (id, tag, tag_type) VALUES (?, ?, 314)", (tag_id, tag_val))
        db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))
        tag_id += 1

    # TV Show hierarchy: Show -> Seasons -> Episodes
    # Breaking Bad (show)
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (100, 2, 2, NULL, 'Breaking Bad', 2008,
           'com.plexapp.agents.thetvdb://81189?lang=en', NULL)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (101, 2, 3, 100, 'Season 1', 2008,
           'com.plexapp.agents.thetvdb://81189/1?lang=en', 1)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (102, 2, 4, 101, 'Pilot', 2008,
           'com.plexapp.agents.thetvdb://81189/1/1?lang=en', 3480000, 1)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (103, 2, 4, 101, 'Cat''s in the Bag', 2008,
           'com.plexapp.agents.thetvdb://81189/1/2?lang=en', 2880000, 2)"""
    )

    # Stranger Things (modern GUID show)
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (110, 2, 2, NULL, 'Stranger Things', 2016,
           'plex://show/5d9c0e8e7e8c1d001e9ae2c1', NULL)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, "index")
           VALUES (111, 2, 3, 110, 'Season 1', 2016,
           'plex://season/5d9c0e8e7e8c1d001e9ae2c2', 1)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (112, 2, 4, 111, 'Chapter One', 2016,
           'plex://episode/5d9c0e8e7e8c1d001e9ae2c3', 2880000, 1)"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid, duration, "index")
           VALUES (113, 2, 4, 111, 'Chapter Two', 2016,
           'plex://episode/5d9c0e8e7e8c1d001e9ae2c4', 3360000, 2)"""
    )

    # External ID tags for Stranger Things show (tag_type=314)
    db.execute("INSERT INTO tags (id, tag, tag_type) VALUES (?, ?, 314)", (tag_id, 'tvdb://305288'))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (110, ?)", (tag_id,))
    tag_id += 1

    # Extra episodes
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

    # Music track
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, parent_id, title, year, guid)
           VALUES (200, 3, 10, NULL, 'Random Album', 2023,
           'com.plexapp.agents.tmdb://9999?lang=en')"""
    )

    # --- Collections (C-A fix: metadata_type=18) ---
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, title, guid)
           VALUES (300, 0, 18, 'Sci-Fi Favorites', 'collection-scifi')"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, title, guid)
           VALUES (301, 0, 18, 'Best of the 90s', 'collection-90s')"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, title, guid)
           VALUES (302, 0, 18, '4K Collection', 'collection-4k')"""
    )
    db.execute(
        """INSERT INTO metadata_items
           (id, library_section_id, metadata_type, title, guid)
           VALUES (303, 0, 18, 'Modern Movies', 'collection-modern')"""
    )

    # Collection membership via tags (tag_type=2, tag = collection title)
    # Real Plex: tags(tag_type=2) stores the collection TITLE, not GUID.
    # Sci-Fi Favorites: Matrix, Inception, Interstellar, Dark Knight
    db.execute("INSERT INTO tags (id, metadata_item_id, tag, tag_type) VALUES (?, ?, ?, 2)", (tag_id, 300, 'Sci-Fi Favorites'))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (1, ?)", (tag_id,))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (2, ?)", (tag_id,))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (3, ?)", (tag_id,))
    db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (4, ?)", (tag_id,))
    tag_id += 1

    # Best of the 90s: Matrix, Pulp Fiction, Fight Club, Forrest Gump, Shawshank
    db.execute("INSERT INTO tags (id, metadata_item_id, tag, tag_type) VALUES (?, ?, ?, 2)", (tag_id, 301, 'Best of the 90s'))
    for mid in [1, 5, 6, 7, 8]:
        db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (?, ?)", (mid, tag_id))
    tag_id += 1

    # Modern Movies: Dune, Everything Everywhere, Oppenheimer
    db.execute("INSERT INTO tags (id, metadata_item_id, tag, tag_type) VALUES (?, ?, ?, 2)", (tag_id, 303, 'Modern Movies'))
    for mid in [20, 21, 22]:
        db.execute("INSERT INTO taggings (metadata_item_id, tag_id) VALUES (?, ?)", (mid, tag_id))
    tag_id += 1

    # 4K Collection: smart, no membership rows (tests L6)

    # --- Custom artwork (C-B fix: *_url columns) ---
    db.execute("UPDATE metadata_items SET user_thumb_url = 'upload://posters/the_matrix_custom' WHERE id = 1")
    db.execute("UPDATE metadata_items SET user_art_url = 'upload://backgrounds/interstellar_bg' WHERE id = 3")
    db.execute("UPDATE metadata_items SET user_thumb_url = 'upload://posters/inception_alt' WHERE id = 2")

    # --- Watch states ---
    watch_states = [
        (1, "com.plexapp.agents.imdb://tt0133093?lang=en", 8.0, 3, 1715000000, 0, 0),
        (1, "com.plexapp.agents.imdb://tt1375666?lang=en", None, 1, 1715000000, 4440000, 0),
        (1, "com.plexapp.agents.imdb://tt0816692?lang=en", 9.0, 2, 1715000000, 0, 0),
        (1, "local://1001", 7.0, 1, 1715000000, 0, 0),
        (1, "com.plexapp.agents.thetvdb://81189/1/1?lang=en", None, 1, 1715000000, 0, 0),
        (1, "com.plexapp.agents.thetvdb://81189/1/2?lang=en", None, 1, 1715000000, 600000, 0),
        (1, "plex://movie/5d77682e3c3f8a001e9ad9b1", 9.0, 2, 1715000000, 0, 0),
        (2, "com.plexapp.agents.imdb://tt0133093?lang=en", 9.5, 5, 1715000000, 0, 0),
        (2, "com.plexapp.agents.tmdb://550?lang=en", 8.0, 2, 1715000000, 0, 0),
        (2, "plex://episode/5d9c0e8e7e8c1d001e9ae2c3", None, 1, 1715000000, 0, 0),
        (2, "com.plexapp.agents.none://abc123", 5.0, 1, 1715000000, 300000, 0),
        (3, "com.plexapp.agents.imdb://tt0133093?lang=en", None, 1, 1715000000, 0, 0),
        (99, "com.plexapp.agents.imdb://tt0133093?lang=en", None, 2, 1715000000, 0, 0),
    ]

    for ws in watch_states:
        db.execute(
            """INSERT INTO metadata_item_settings
               (account_id, guid, rating, view_count, last_viewed_at, view_offset, skip_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ws,
        )

    db.commit()
    db.close()
    print(f"Test fixture created: {DB_PATH}")


if __name__ == "__main__":
    create_test_db()
