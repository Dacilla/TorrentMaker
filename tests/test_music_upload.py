"""Tests for music upload scanning and RED/OPS payload construction."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _write_album(tmp_path, names):
    album = tmp_path / "Album"
    album.mkdir()
    for name in names:
        (album / name).write_bytes(b"audio")
    (album / "cover.jpg").write_bytes(b"jpg")
    return album


def _fake_mutagen_factory(track_tags, tech):
    def fake_file(path, easy=False):
        name = path.name if hasattr(path, "name") else str(path).split("\\")[-1].split("/")[-1]
        if easy:
            return track_tags[name]
        return tech[name]
    return fake_file


def _easy(track, total, *, genre="pop", artist="D'Leesa", album="Desire", title=None, date="2025-10-10", copyright_text="D'Leesa"):
    return {
        "albumartist": [artist],
        "artist": [artist],
        "album": [album],
        "title": [title or f"Track {track}"],
        "date": [date],
        "tracknumber": [f"{track}/{total}"],
        "genre": [genre] if genre is not None else [],
        "copyright": [copyright_text],
    }


def _tech(audio_format="FLAC", bitrate=320000, bits=16, md5=b"1"):
    if audio_format == "FLAC":
        return SimpleNamespace(mime=["audio/flac"], info=SimpleNamespace(bits_per_sample=bits, md5_signature=md5))
    return SimpleNamespace(mime=["audio/mp3"], info=SimpleNamespace(bitrate=bitrate))


def _payload_values(payload, key):
    return [value for item_key, value in payload if item_key == key]


class TestScanAlbum:
    def test_scan_ready_flac_album(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.flac", "02.flac", "03.flac"])
        tags = {
            "01.flac": _easy(1, 3),
            "02.flac": _easy(2, 3),
            "03.flac": _easy(3, 3),
        }
        tech = {name: _tech("FLAC") for name in tags}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album), media="WEB")

        assert scan.ok
        assert scan.metadata.artist == "D'Leesa"
        assert scan.metadata.title == "Desire"
        assert scan.metadata.year == 2025
        assert scan.metadata.release_type == "EP"
        assert scan.metadata.audio_format == "FLAC"
        assert scan.metadata.bitrate == "Lossless"
        assert scan.metadata.tags == "pop"
        assert scan.metadata.record_label == "Self-Released"

    def test_scan_flags_missing_flac_md5_for_prompt(self, tmp_path, monkeypatch):
        import musicTorrentMaker
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.flac"])
        tags = {"01.flac": _easy(1, 1)}
        tech = {"01.flac": _tech("FLAC", md5=b"")}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album), media="WEB")

        assert musicTorrentMaker.scan_has_missing_md5(scan)
        assert "one or more FLAC files have missing MD5 signatures" in scan.blockers
        assert scan.tracks[0].md5_missing

    def test_missing_genre_blocks_upload_readiness(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.mp3"])
        tags = {"01.mp3": _easy(1, 1, genre=None)}
        tech = {"01.mp3": _tech("MP3", bitrate=320000)}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album))

        assert "missing genre/tags" in scan.blockers

    def test_tags_override_satisfies_missing_genre(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.mp3"])
        tags = {"01.mp3": _easy(1, 1, genre=None)}
        tech = {"01.mp3": _tech("MP3", bitrate=320000)}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album), tags_override="Pop, Dance")

        assert scan.ok
        assert scan.metadata.tags == "pop, dance"

    def test_mixed_formats_block(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.flac", "02.mp3"])
        tags = {
            "01.flac": _easy(1, 2),
            "02.mp3": _easy(2, 2),
        }
        tech = {"01.flac": _tech("FLAC"), "02.mp3": _tech("MP3")}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album))

        assert "mixed audio formats in one folder" in scan.blockers

    def test_missing_track_number_blocks(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.flac", "03.flac"])
        tags = {
            "01.flac": _easy(1, 3),
            "03.flac": _easy(3, 3),
        }
        tech = {name: _tech("FLAC") for name in tags}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album))

        assert "missing track 2 on disc 1" in scan.blockers

    def test_cd_media_blocks_until_log_upload_support_exists(self, tmp_path, monkeypatch):
        from torrent_utils import music_upload

        album = _write_album(tmp_path, ["01.flac"])
        tags = {"01.flac": _easy(1, 1)}
        tech = {"01.flac": _tech("FLAC")}
        monkeypatch.setattr(music_upload.mutagen, "File", _fake_mutagen_factory(tags, tech))

        scan = music_upload.scan_album(str(album), media="CD")

        assert "CD uploads require log/CUE attachment support before upload" in scan.blockers


class TestPayloadBuilders:
    def _metadata(self):
        from torrent_utils.music_upload import MusicUploadMetadata

        return MusicUploadMetadata(
            artist="D'Leesa, Guest",
            title="Desire",
            year=2025,
            release_type="Album",
            audio_format="FLAC",
            bitrate="Lossless",
            media="WEB",
            tags="pop, dance",
            image="https://ptpimg.me/cover.jpg",
            record_label="Self-Released",
            edition_year=2026,
        )

    def test_red_payload_uses_repeated_artist_fields_and_dryrun(self):
        from torrent_utils.music_upload import build_red_payload

        payload = build_red_payload(self._metadata(), "tracks", group_id=123, dryrun=True)

        assert ("dryrun", 1) in payload
        assert ("groupid", 123) in payload
        assert ("year", 2025) in payload
        assert ("remaster_year", 2026) in payload
        assert ("remaster_record_label", "Self-Released") in payload
        assert _payload_values(payload, "artists[]") == ["D'Leesa", "Guest"]
        assert _payload_values(payload, "importance[]") == [1, 1]
        assert _payload_values(payload, "tags") == ["pop, dance, 2020s"]

    def test_red_payload_pairs_record_label_with_release_year_when_no_edition_year(self):
        from dataclasses import replace
        from torrent_utils.music_upload import build_red_payload

        metadata = replace(self._metadata(), edition_year=None)

        payload = build_red_payload(metadata, "tracks")

        assert ("year", 2025) in payload
        assert ("remaster_year", 2025) in payload
        assert ("remaster_record_label", "Self-Released") in payload

    def test_ops_payload_uses_initial_year_and_edition_year(self):
        from torrent_utils.music_upload import build_ops_payload

        payload = build_ops_payload(self._metadata(), "tracks", group_id=456)

        assert ("groupid", 456) in payload
        assert ("year", 2025) in payload
        assert ("remaster", 1) in payload
        assert ("remaster_year", 2026) in payload
        assert ("record_label", "Self-Released") in payload
        assert ("remaster_record_label", "Self-Released") in payload
        assert _payload_values(payload, "artists[]") == ["D'Leesa", "Guest"]

    def test_ops_payload_pairs_record_label_with_release_year_when_no_edition_year(self):
        from dataclasses import replace
        from torrent_utils.music_upload import build_ops_payload

        metadata = replace(self._metadata(), edition_year=None)

        payload = build_ops_payload(metadata, "tracks")

        assert ("year", 2025) in payload
        assert ("remaster", 1) in payload
        assert ("remaster_year", 2025) in payload
        assert ("record_label", "Self-Released") in payload
        assert ("remaster_record_label", "Self-Released") in payload

    def test_missing_image_fails_payload_build(self):
        from torrent_utils.music_upload import build_red_payload
        from dataclasses import replace

        metadata = replace(self._metadata(), image="")

        with pytest.raises(ValueError, match="missing uploaded image URL"):
            build_red_payload(metadata, "tracks")

    def test_identity_key_differentiates_same_title_different_year(self):
        from dataclasses import replace

        first = self._metadata()
        second = replace(first, year=2026)

        assert first.identity_key != second.identity_key


class TestRedUploadRunner:
    def test_first_duplicate_group_id_reads_red_browse_keys(self):
        import musicTorrentMaker

        assert musicTorrentMaker.first_duplicate_group_id([{"groupId": 123}]) == 123
        assert musicTorrentMaker.first_duplicate_group_id([{"groupID": "456"}]) == "456"
        assert musicTorrentMaker.first_duplicate_group_id([{"torrentId": 789}]) is None

    def test_tracker_response_indicates_existing_upload(self):
        import musicTorrentMaker

        assert musicTorrentMaker.tracker_response_indicates_existing({
            "status": "failure",
            "error": "This torrent already exists.",
        })
        assert not musicTorrentMaker.tracker_response_indicates_existing({
            "status": "failure",
            "error": "Year of remaster/re-issue must be entered.",
        })

    def test_format_missing_md5_files_limits_output(self):
        import musicTorrentMaker

        tracks = [
            SimpleNamespace(path=f"C:/Music/{idx:02d}.flac", md5_missing=True)
            for idx in range(1, 8)
        ]
        scan = SimpleNamespace(tracks=tracks)

        assert musicTorrentMaker._format_missing_md5_files(scan) == (
            "01.flac, 02.flac, 03.flac, 04.flac, 05.flac, and 2 more"
        )

    def test_prepend_description_adds_prefix_with_blank_line(self):
        import musicTorrentMaker

        assert musicTorrentMaker.prepend_description("01. Track", "Sourced from Amazon Music") == "Sourced from Amazon Music\n\n01. Track"
        assert musicTorrentMaker.prepend_description("01. Track", "  ") == "01. Track"

    def test_create_tracker_torrent_file_writes_single_announce_and_source(self, tmp_path):
        import torf
        import musicTorrentMaker

        album = tmp_path / "Album"
        run_dir = tmp_path / "run"
        album.mkdir()
        run_dir.mkdir()
        (album / "01.flac").write_bytes(b"audio")

        torrent_name = musicTorrentMaker.tracker_torrent_filename("Album.torrent", "RED")
        written_name = musicTorrentMaker.create_torrent_file(
            str(album),
            str(run_dir),
            torrent_name,
            "https://flacsfor.me/passkey/announce",
            "RED",
            "REDacted",
        )

        torrent = torf.Torrent.read(str(run_dir / written_name))
        assert written_name == "Album [RED].torrent"
        assert torrent.trackers == [["https://flacsfor.me/passkey/announce"]]
        assert torrent.source == "RED"
        assert torrent.private is True

    def test_red_upload_runs_dryrun_before_real_upload(self, tmp_path):
        import musicTorrentMaker

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "trackData.txt").write_text("tracks", encoding="utf-8")
        torrent_file = run_dir / "album.torrent"
        torrent_file.write_bytes(b"torrent")

        dryrun_response = MagicMock()
        dryrun_response.raise_for_status.return_value = None
        dryrun_response.json.return_value = {"status": "dry run success", "data": {}}
        real_response = MagicMock()
        real_response.raise_for_status.return_value = None
        real_response.json.return_value = {"status": "success", "response": {"groupid": 123}}

        with patch("musicTorrentMaker.requests.post", side_effect=[dryrun_response, real_response]) as post:
            response = musicTorrentMaker.upload_to_red(
                runDir=str(run_dir),
                releaseGroup=None,
                torrent_file=str(torrent_file),
                artists="D'Leesa",
                title="Desire",
                year=2025,
                releasetype="Album",
                audioFormat="MP3",
                bitrate="320",
                media="WEB",
                tags="pop",
                image="https://ptpimg.me/cover.jpg",
                api="red-api",
                recordLabel="Self-Released",
                skipPrompts=True,
                dry_run=True,
                desc_prefix="Sourced from Amazon Music",
            )

        assert response is real_response
        assert post.call_count == 2
        assert post.call_args_list[0].kwargs["url"] == "https://redacted.sh/ajax.php?action=upload"
        assert post.call_args_list[1].kwargs["url"] == "https://redacted.sh/ajax.php?action=upload"
        assert ("dryrun", 1) in post.call_args_list[0].kwargs["data"]
        assert ("dryrun", 1) not in post.call_args_list[1].kwargs["data"]
        assert ("album_desc", "Sourced from Amazon Music\n\ntracks") in post.call_args_list[1].kwargs["data"]

    def test_red_upload_treats_dryrun_existing_as_complete(self, tmp_path):
        import musicTorrentMaker

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "trackData.txt").write_text("tracks", encoding="utf-8")
        torrent_file = run_dir / "album.torrent"
        torrent_file.write_bytes(b"torrent")

        dryrun_response = MagicMock()
        dryrun_response.raise_for_status.return_value = None
        dryrun_response.status_code = 200
        dryrun_response.json.return_value = {
            "status": "failure",
            "error": "This torrent already exists.",
        }

        with patch("musicTorrentMaker.requests.post", return_value=dryrun_response) as post:
            response = musicTorrentMaker.upload_to_red(
                runDir=str(run_dir),
                releaseGroup=None,
                torrent_file=str(torrent_file),
                artists="D'Leesa",
                title="Desire",
                year=2025,
                releasetype="Album",
                audioFormat="MP3",
                bitrate="320",
                media="WEB",
                tags="pop",
                image="https://ptpimg.me/cover.jpg",
                api="red-api",
                recordLabel="Self-Released",
                skipPrompts=True,
                dry_run=True,
            )

        assert response is dryrun_response
        assert post.call_count == 1

    def test_ops_upload_prepends_description(self, tmp_path):
        import musicTorrentMaker

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "trackData.txt").write_text("tracks", encoding="utf-8")
        torrent_file = run_dir / "album.torrent"
        torrent_file.write_bytes(b"torrent")

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"status": "success", "response": {"groupId": 456}}

        with patch("musicTorrentMaker.requests.post", return_value=response) as post:
            result = musicTorrentMaker.upload_to_orpheus(
                runDir=str(run_dir),
                torrent_file=str(torrent_file),
                artists="D'Leesa",
                title="Desire",
                year=2025,
                releasetype="Album",
                audioFormat="MP3",
                bitrate="320",
                media="WEB",
                tags="pop",
                image="https://ptpimg.me/cover.jpg",
                api="ops-api",
                recordLabel="Self-Released",
                skipPrompts=True,
                desc_prefix="Sourced from Amazon Music",
            )

        assert result is response
        assert ("album_desc", "Sourced from Amazon Music\n\ntracks") in post.call_args.kwargs["data"]


class TestMusicCliHelpers:
    def test_expand_collection_root_to_album_folders(self, tmp_path):
        import musicTorrentMaker

        root = tmp_path / "collection"
        album_a = root / "Artist - A"
        album_b = root / "Artist - B"
        album_a.mkdir(parents=True)
        album_b.mkdir()
        (album_a / "01.flac").write_bytes(b"audio")
        (album_b / "01.mp3").write_bytes(b"audio")

        assert musicTorrentMaker.expand_music_paths([str(root)]) == [str(album_a), str(album_b)]

    def test_expand_preserves_multi_disc_album_root(self, tmp_path):
        import musicTorrentMaker

        root = tmp_path / "Album"
        disc = root / "Disc 1"
        disc.mkdir(parents=True)
        (disc / "01.flac").write_bytes(b"audio")

        assert musicTorrentMaker.expand_music_paths([str(root)]) == [str(root)]

    def test_duplicate_lookup_returns_browse_results(self):
        import musicTorrentMaker

        metadata = MagicMock()
        metadata.artist = "D'Leesa"
        metadata.title = "Desire"
        metadata.year = 2025
        metadata.audio_format = "FLAC"
        metadata.bitrate = "Lossless"
        metadata.media = "WEB"

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"status": "success", "response": {"results": [{"groupId": 1}]}}

        with patch("musicTorrentMaker.requests.get", return_value=response) as get:
            assert musicTorrentMaker.search_tracker_duplicates("red", "api", metadata) == [{"groupId": 1}]

        assert get.call_args.args[0] == "https://redacted.sh/ajax.php?action=browse"
