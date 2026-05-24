"""Tests for Plex reader and CLI."""

import json
import os
import tempfile
import sys
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent
FIXTURE_DB = FIXTURE_DIR / "plex-test.db"

class TestGuidParsing:
    def test_legacy_imdb(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'com.plexapp.agents.imdb://tt0133093?lang=en'
        )
        assert provider == 'imdb'
        assert guid_id == 'tt0133093'
        assert fmt == 'legacy'

    def test_legacy_tmdb(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'com.plexapp.agents.tmdb://680?lang=en'
        )
        assert provider == 'tmdb'
        assert guid_id == '680'
        assert fmt == 'legacy'

    def test_legacy_thetvdb_normalizes(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'com.plexapp.agents.thetvdb://81189/1/1?lang=en'
        )
        assert provider == 'tvdb'
        assert guid_id == '81189'
        assert fmt == 'legacy'

    def test_legacy_themoviedb_normalizes(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'com.plexapp.agents.themoviedb://12345?lang=en'
        )
        assert provider == 'tmdb'
        assert guid_id == '12345'
        assert fmt == 'legacy'

    def test_local_guid(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid('local://1001')
        assert provider == 'local'
        assert guid_id == '1001'
        assert fmt == 'local'

    def test_modern_movie_guid(self):
        """C1 fix: modern plex://movie GUID recognized but needs DB lookup."""
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'plex://movie/5d77682e3c3f8a001e9ad9b1'
        )
        assert provider is None  # no external ID in GUID string
        assert guid_id is None
        assert fmt == 'modern'

    def test_modern_episode_guid(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'plex://episode/5d9c0e8e7e8c1d001e9ae2c3'
        )
        assert provider is None
        assert guid_id is None
        assert fmt == 'modern'

    def test_modern_show_guid(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid(
            'plex://show/5d9c0e8e7e8c1d001e9ae2c1'
        )
        assert provider is None
        assert guid_id is None
        assert fmt == 'modern'

    def test_unknown_guid(self):
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid('com.plexapp.agents.none://abc123')
        assert provider == 'none'
        assert guid_id == 'abc123'
        assert fmt == 'legacy'

    def test_malformed_guid(self):
        """Edge case: completely unrecognizable GUID."""
        from switchkit.plex_reader import parse_guid
        provider, guid_id, fmt = parse_guid('garbage_string')
        assert provider is None
        assert guid_id is None
        assert fmt is None

    def test_external_tag_parsing(self):
        from switchkit.plex_reader import _parse_external_tag
        provider, ext_id = _parse_external_tag('imdb://tt1234567')
        assert provider == 'imdb'
        assert ext_id == 'tt1234567'

        provider, ext_id = _parse_external_tag('tmdb://12345')
        assert provider == 'tmdb'
        assert ext_id == '12345'

        provider, ext_id = _parse_external_tag('tvdb://81189')
        assert provider == 'tvdb'
        assert ext_id == '81189'

        # Bad tags
        provider, ext_id = _parse_external_tag('garbage')
        assert provider is None
        assert ext_id is None


class TestPlexReader:
    @pytest.fixture
    def reader(self):
        from switchkit.plex_reader import PlexReader
        reader = PlexReader(str(FIXTURE_DB))
        reader.open()
        yield reader
        reader.close()

    def test_version(self, reader):
        assert reader.get_version() == '140'

    def test_users(self, reader):
        users = reader.get_users()
        assert len(users) == 4  # 3 local + 1 external (account_id=99)
        names = {u.name for u in users}
        assert 'admin' in names
        assert 'sarah' in names
        assert 'Managed User:guest' in names

        managed = [u for u in users if u.is_managed]
        assert len(managed) == 1
        assert managed[0].name == 'Managed User:guest'

        external = [u for u in users if u.is_external]
        assert len(external) == 1
        assert external[0].name == 'External User 99'

    def test_libraries_includes_music(self, reader):
        """C1/H2 fix: Music library should not be dropped."""
        libraries = reader.get_libraries()
        assert len(libraries) == 3  # Movies, TV Shows, Music
        lib_names = {lib.name for lib in libraries}
        assert 'Movies' in lib_names
        assert 'TV Shows' in lib_names
        assert 'Music' in lib_names

        movies = next(lib for lib in libraries if lib.name == 'Movies')
        assert movies.section_type == 'movie'

        music = next(lib for lib in libraries if lib.name == 'Music')
        assert music.section_type == 'music'

    def test_guid_format_distribution(self, reader):
        """C1 fix: diagnostic shows both legacy and modern GUIDs."""
        dist = reader.get_guid_format_distribution()
        # Should have both legacy and modern GUIDs
        assert 'legacy' in dist
        assert 'modern' in dist
        assert dist['legacy'] > 0
        assert dist['modern'] > 0

    def test_modern_guid_resolution(self, reader):
        """C1 fix: modern plex:// GUID resolves to external ID via tags."""
        reader._load_external_ids()
        # Dune (id=20) has tmdb://438631
        provider, ext_id = reader._resolve_external_id(20)
        assert provider == 'tmdb'
        assert ext_id == '438631'

        # Everything Everywhere (id=21) has both imdb and tmdb, should prefer tmdb
        provider, ext_id = reader._resolve_external_id(21)
        assert provider == 'tmdb'
        # should have an external ID from the preloaded cache
        assert ext_id is not None

    def test_watch_states_include_external_users(self, reader):
        """M1 fix: external user (id=99) watch states included (deduped per H-B)."""
        states = reader.get_watch_states()
        external_states = [s for s in states if s.user_id == 99]
        assert len(external_states) == 1  # H-B dedup: one per GUID
        assert 'External User 99' in external_states[0].user_name

    def test_watch_states_tv_episode_identity(self, reader):
        """C2 fix: TV episodes carry show title, season number, episode number."""
        states = reader.get_watch_states()
        episodes = [s for s in states if s.media_type == 'episode']

        # Breaking Bad S01E01 (Pilot) — has parent/grandparent
        pilot = [s for s in episodes if s.title == 'Pilot']
        assert len(pilot) == 1, f"Expected 1 Pilot episode, got {len(pilot)}"
        ws = pilot[0]
        assert ws.show_title == 'Breaking Bad'
        assert ws.season_number == 1
        assert ws.episode_number == 1

        # Breaking Bad S01E02
        cats = [s for s in episodes if "Cat's" in s.title]
        assert len(cats) == 1, f"Expected 1 'Cat's' episode, got {len(cats)}"
        ws = cats[0]
        assert ws.show_title == 'Breaking Bad'
        assert ws.season_number == 1
        assert ws.episode_number == 2

    def test_modern_guid_watch_states_resolved(self, reader):
        """C1 fix: modern GUID watch states resolve external IDs from DB.

        Movies: external IDs on the movie metadata item.
        TV episodes: external IDs on the grandparent SHOW, not the episode.
        """
        states = reader.get_watch_states()

        # Dune watch state (admin) — movie, modern GUID, resolves from own tags
        dune = [s for s in states if s.title == 'Dune']
        assert len(dune) >= 1
        dune_ws = dune[0]
        assert dune_ws.guid_format == 'modern'
        assert dune_ws.guid_provider == 'tmdb'
        assert dune_ws.guid_id == '438631'

        # Stranger Things S01E01 (sarah) — episode, modern GUID
        # External ID should resolve from the grandparent SHOW (id=110), not the episode
        st_ep = [s for s in states if s.title == 'Chapter One']
        assert len(st_ep) >= 1
        st_ws = st_ep[0]
        assert st_ws.guid_format == 'modern'
        assert st_ws.media_type == 'episode'
        # Should resolve from Stranger Things show (id=110) which has tvdb://305288
        assert st_ws.guid_provider == 'tvdb'
        assert st_ws.show_title == 'Stranger Things'

    def test_watch_states_count(self, reader):
        states = reader.get_watch_states()
        # H-B dedup: The Matrix (non-4K and 4K copy share GUID — dedup picks one)
        # admin: 7, sarah: 4, guest: 1, external 99: 1 = 13
        assert len(states) == 13

    def test_collections(self, reader):
        collections = reader.get_collections()
        # C-A fix: 5 collections (Sci-Fi, 90s, 4K smart, Modern Movies, Awesome Shows)
        assert len(collections) == 5
        titles = {c.title for c in collections}
        assert 'Sci-Fi Favorites' in titles
        assert 'Best of the 90s' in titles
        assert '4K Collection' in titles
        assert 'Modern Movies' in titles

    def test_custom_artwork(self, reader):
        """H1 fix: artwork queries user_thumb/user_art, not media_parts."""
        artwork = reader.get_custom_artwork()
        assert len(artwork) == 3  # The Matrix, Inception, Interstellar
        # All should have upload:// URIs and correct artwork_type
        for a in artwork:
            assert a.file.startswith('upload://')
            assert a.artwork_type in ('poster', 'background')

        # Check specific items
        matrix_art = next(a for a in artwork if a.metadata_item_id == 1)
        assert matrix_art.artwork_type == 'poster'

        interstellar_art = next(a for a in artwork if a.metadata_item_id == 3)
        assert interstellar_art.artwork_type == 'background'

    def test_collection_memberships(self, reader):
        """M6 fix: collection memberships resolved to external IDs."""
        memberships = reader.get_collection_memberships()
        # Should have the collection items we inserted, including modern Dune + TV episode
        assert len(memberships) == 13  # 9 from originals + 3 from Modern Movies + 1 TV episode

        # Verify legacy movie in collection (The Matrix, id=1, in collection 1 and 2)
        matrix_m = [m for m in memberships if m['metadata_item_id'] == 1]
        assert len(matrix_m) == 2
        for m in matrix_m:
            assert m['external_id_provider'] == 'imdb'
            assert m['external_id'] == 'tt0133093'

        # Verify modern movie in collection (Dune, id=20, in Modern Movies)
        dune_m = [m for m in memberships if m['metadata_item_id'] == 20]
        assert len(dune_m) == 1
        assert dune_m[0]['collection_title'] == 'Modern Movies'
        assert dune_m[0]['external_id_provider'] == 'tmdb'
        assert dune_m[0]['external_id'] == '438631'

    def test_collection_membership_tv_episode_resolves_show_external_id(self, reader):
        """M2 fix: modern TV episodes in collections resolve external IDs from grandparent show."""
        memberships = reader.get_collection_memberships()
        episodes = [m for m in memberships
                    if m['show_title'] == 'Stranger Things' and m['media_type'] == 'episode']
        assert len(episodes) >= 1, \
            f"Expected at least 1 Stranger Things episode in collection, got {len(episodes)}"
        ep = episodes[0]
        assert ep['external_id_provider'] is not None, \
            f"TV episode in collection should resolve external ID from show, got provider=None"
        assert ep['external_id'] is not None, \
            f"TV episode in collection should resolve external ID from show, got id=None"
        assert ep['show_title'] == 'Stranger Things'
        assert ep['season_number'] == 1
        assert ep['episode_number'] == 1

    def test_diagnostics(self, reader):
        diag = reader.get_diagnostics()
        assert diag['schema_version'] == '140'
        assert 'guid_format_distribution' in diag
        assert diag['total_settings_rows'] > 0
        assert diag['migratable_settings_rows'] > 0
        assert 'joined_watch_states' in diag
        assert 'unjoined_watch_states' in diag

    def test_all_stats_external_id_terminology(self, reader):
        """H4 fix: uses 'external ID present/absent' not 'matched/unmatched'."""
        stats = reader.get_all_stats()
        assert 'watch_states_external_id_present' in stats
        assert 'watch_states_external_id_missing' in stats
        # Old keys should NOT exist
        assert 'watch_states_matched' not in stats
        assert 'watch_states_unmatched' not in stats

    def test_nonexistent_db(self):
        from switchkit.plex_reader import PlexReader
        reader = PlexReader("/nonexistent/path.db")
        with pytest.raises(FileNotFoundError):
            reader.open()

    def test_not_a_plex_db(self):
        from switchkit.plex_reader import PlexReader
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            f.write(b"not a sqlite db")
            path = f.name
        try:
            reader = PlexReader(path)
            with pytest.raises((ValueError, Exception)):
                reader.open()
        finally:
            os.unlink(path)

    def test_path_with_spaces(self, tmp_path):
        """C1/H8 fix: paths with spaces don't break URI construction."""
        from switchkit.plex_reader import PlexReader
        import shutil
        spaced_path = tmp_path / "plex test db.db"
        shutil.copy(FIXTURE_DB, spaced_path)
        reader = PlexReader(str(spaced_path))
        reader.open()
        assert reader.get_version() == '140'
        reader.close()


class TestCLI:
    def test_inspect_command(self, tmp_path):
        """C4 fix: 'inspect' is the command, not 'migrate --dry-run'."""
        import subprocess
        output_path = tmp_path / "plan.json"
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(FIXTURE_DB),
             "--output", str(output_path)],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Inspect complete" in result.stderr
        assert "read-only" in result.stderr.lower()

    def test_inspect_plan_has_privacy_warning(self, tmp_path):
        import subprocess
        output_path = tmp_path / "plan.json"
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(FIXTURE_DB),
             "--output", str(output_path)],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode == 0

        with open(output_path) as f:
            plan = json.load(f)

        assert '_WARNING' in plan
        assert 'viewing history' in plan['_WARNING'].lower()
        assert plan['mode'] == 'inspect'

    def test_inspect_plan_structure(self, tmp_path):
        import subprocess
        output_path = tmp_path / "plan.json"
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(FIXTURE_DB),
             "--output", str(output_path)],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode == 0

        with open(output_path) as f:
            plan = json.load(f)

        assert plan['mode'] == 'inspect'
        assert 'watch_states_external_id_present' in plan
        assert 'watch_states_external_id_missing' in plan
        assert 'users' in plan
        assert 'libraries' in plan
        assert 'collections' in plan
        assert 'diagnostics' in plan

    def test_output_path_validation_blocks_traversal(self, tmp_path):
        """C6 fix: relative --output with ../ traversal is rejected."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(FIXTURE_DB),
             "--output", "../../../etc/passwd"],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode != 0

    def test_output_path_requires_json_extension(self, tmp_path):
        """C6 fix: --output must have .json extension."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(FIXTURE_DB),
             "--output", str(tmp_path / "plan.txt")],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode != 0

    def test_nonexistent_db_fails(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", "/nonexistent/db"],
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode != 0

    def test_directory_not_file_fails(self, tmp_path):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "switchkit.cli",
             "inspect",
             "--plex-db", str(tmp_path)],  # directory, not file
            capture_output=True, text=True,
            cwd=str(FIXTURE_DIR.parent),
        )
        assert result.returncode != 0
