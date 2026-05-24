"""Edge-case tests: unicode, corrupt data, special characters."""
import sqlite3, os, tempfile, pytest

@pytest.fixture
def tmp_db():
    """Create a DB with edge-case data."""
    path = tempfile.mktemp(suffix='.db')
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO schema_migrations VALUES (140)")
    db.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO accounts VALUES (1, 'test_user')")
    db.execute("CREATE TABLE library_sections (id INTEGER PRIMARY KEY, name TEXT, section_type INTEGER, created_at INTEGER DEFAULT 0)")
    db.execute("INSERT INTO library_sections VALUES (1, 'Movies', 1, 0)")
    db.execute("""CREATE TABLE metadata_items (
        id INTEGER PRIMARY KEY, library_section_id INTEGER, metadata_type INTEGER,
        parent_id INTEGER, title TEXT, year INTEGER, guid TEXT,
        added_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0,
        "index" INTEGER, user_thumb_url TEXT, user_art_url TEXT
    )""")
    db.execute("""CREATE TABLE metadata_item_settings (
        id INTEGER PRIMARY KEY, account_id INTEGER, guid TEXT,
        rating REAL, view_count INTEGER DEFAULT 0, last_viewed_at INTEGER,
        view_offset INTEGER DEFAULT 0, skip_count INTEGER DEFAULT 0
    )""")
    db.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, metadata_item_id INTEGER, tag TEXT, tag_type INTEGER, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)")
    db.execute("CREATE TABLE taggings (id INTEGER PRIMARY KEY, metadata_item_id INTEGER, tag_id INTEGER)")
    db.commit()
    db.close()
    yield path
    os.unlink(path)


def test_unicode_titles(tmp_db):
    """Titles with emoji, RTL text, and special characters."""
    from switchkit.plex_reader import PlexReader

    db = sqlite3.connect(tmp_db)
    titles = [
        (1, "🎬 The Movie", "com.plexapp.agents.imdb://tt0000001?lang=en"),
        (2, "فيلم عربي", "com.plexapp.agents.imdb://tt0000002?lang=en"),
        (3, "кино", "com.plexapp.agents.imdb://tt0000003?lang=en"),
        (4, "日本映画", "com.plexapp.agents.imdb://tt0000004?lang=en"),
        (5, "O'Malley's \"Best\" Film", "com.plexapp.agents.imdb://tt0000005?lang=en"),
    ]
    for mid, title, guid in titles:
        db.execute("INSERT INTO metadata_items (id, library_section_id, metadata_type, title, guid) VALUES (?,1,1,?,?)",
                   (mid, title, guid))
    db.execute("INSERT INTO metadata_item_settings (account_id, guid, view_count) VALUES (1, 'com.plexapp.agents.imdb://tt0000001?lang=en', 1)")
    db.commit()
    db.close()

    reader = PlexReader(tmp_db)
    reader.open()
    try:
        states = reader.get_watch_states()
        assert len(states) == 1
        assert states[0].title == "🎬 The Movie"
    finally:
        reader.close()


def test_null_and_empty_data(tmp_db):
    """Handle NULL values and empty strings gracefully."""
    from switchkit.plex_reader import PlexReader

    db = sqlite3.connect(tmp_db)
    db.execute("INSERT INTO metadata_items (id, library_section_id, metadata_type, title, guid) VALUES (1,1,1,NULL,'local://null_title')")
    db.execute("INSERT INTO metadata_item_settings (account_id, guid, rating, view_offset) VALUES (1,'local://null_title',NULL,NULL)")
    db.commit()
    db.close()

    reader = PlexReader(tmp_db)
    reader.open()
    try:
        states = reader.get_watch_states()
        assert len(states) == 0  # view_count=0, view_offset=NULL, rating=NULL — not migratable
    finally:
        reader.close()


def test_malformed_guid(tmp_db):
    """Malformed GUIDs shouldn't crash the parser."""
    from switchkit.plex_reader import PlexReader

    db = sqlite3.connect(tmp_db)
    guids = [
        (1, "garbage", "garbage"),
        (2, "", ""),
        (3, "plex://movie/", "plex://movie/"),
        (4, "com.plexapp.agents.imdb://", "com.plexapp.agents.imdb://"),
        (5, "a" * 1000, "a" * 1000),
    ]
    for mid, guid, title in guids:
        db.execute("INSERT INTO metadata_items (id, library_section_id, metadata_type, title, guid) VALUES (?,1,1,?,?)",
                   (mid, title, guid))
    db.execute("INSERT INTO metadata_item_settings (account_id, guid, view_count) VALUES (1,'garbage',1)")
    db.commit()
    db.close()

    reader = PlexReader(tmp_db)
    reader.open()
    try:
        states = reader.get_watch_states()
        assert len(states) == 1
        assert states[0].guid_provider is None
    finally:
        reader.close()


def test_corrupt_db(tmp_db):
    """Corrupt SQLite file should raise clear error, not crash."""
    from switchkit.plex_reader import PlexReader
    import pytest

    corrupt = tmp_db + '.corrupt'
    with open(corrupt, 'wb') as f:
        f.write(b'this is not a sqlite database')

    reader = PlexReader(corrupt)
    with pytest.raises(ValueError, match="Not a valid Plex database"):
        reader.open()
    os.unlink(corrupt)


def test_empty_db(tmp_db):
    """Empty but valid DB should return empty results, not crash."""
    from switchkit.plex_reader import PlexReader

    reader = PlexReader(tmp_db)
    reader.open()
    try:
        # Fixture has 1 user, but no watch states/collections/artwork
        assert len(reader.get_users()) == 1
        assert reader.get_watch_states() == []
        assert reader.get_collections() == []
        assert reader.get_custom_artwork() == []
        # Diagnostics should not crash or produce negatives
        d = reader.get_diagnostics()
        assert d['unjoined_watch_states'] >= 0
    finally:
        reader.close()


def test_duplicate_settings_guid(tmp_db):
    """Same GUID, same account, multiple settings rows — no fanout crash."""
    from switchkit.plex_reader import PlexReader

    db = sqlite3.connect(tmp_db)
    db.execute("INSERT INTO metadata_items (id, library_section_id, metadata_type, title, guid) VALUES (1,1,1,'Test','com.plexapp.agents.imdb://tt0000001?lang=en')")
    db.execute("INSERT INTO metadata_item_settings (account_id, guid, view_count) VALUES (1,'com.plexapp.agents.imdb://tt0000001?lang=en',1)")
    db.execute("INSERT INTO metadata_item_settings (account_id, guid, view_count) VALUES (1,'com.plexapp.agents.imdb://tt0000001?lang=en',2)")
    db.commit()
    db.close()

    reader = PlexReader(tmp_db)
    reader.open()
    try:
        states = reader.get_watch_states()
        # Two settings rows for same user+guid — both should appear
        assert len(states) == 2
    finally:
        reader.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
