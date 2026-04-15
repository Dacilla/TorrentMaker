"""Tests for torrent_utils/media.py — all external calls mocked."""
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers to build a minimal pymediainfo-style JSON structure
# ---------------------------------------------------------------------------

def _make_media_info(video: dict = None, audio: dict = None, audio_tracks: list = None):
    """Return a fake media_info dict matching the pymediainfo JSON schema.

    Pass *audio* for a single audio track, or *audio_tracks* for multiple.
    """
    tracks = [{"@type": "General"}]
    if video:
        t = {"@type": "Video"}
        t.update(video)
        tracks.append(t)
    if audio:
        t = {"@type": "Audio"}
        t.update(audio)
        tracks.append(t)
    for extra in (audio_tracks or []):
        t = {"@type": "Audio"}
        t.update(extra)
        tracks.append(t)
    return {"media": {"track": tracks}}


def _make_media_file(filename="test.mkv", media_info=None):
    """Construct a MediaFile with mocked pymediainfo and guessit."""
    from torrent_utils.media import MediaFile
    with patch("torrent_utils.media.MediaInfo.parse", return_value="{}"), \
         patch("torrent_utils.media.json.loads", return_value=media_info or {}), \
         patch("torrent_utils.media.guessit.guessit", return_value={}):
        obj = MediaFile.__new__(MediaFile)
        obj.path = filename
        obj.filename = filename
        obj.media_info = media_info or {}
        obj.guessit_info = {}
    return obj


# ---------------------------------------------------------------------------
# get_resolution
# ---------------------------------------------------------------------------

class TestGetResolution:
    def _file(self, width, height, scan_type=None):
        video = {"Width": str(width), "Height": str(height)}
        if scan_type:
            video["ScanType"] = scan_type
        return _make_media_file(media_info=_make_media_info(video=video))

    def test_1080p(self):
        assert self._file(1920, 1080).get_resolution() == "1080p"

    def test_720p(self):
        assert self._file(1280, 720).get_resolution() == "720p"

    def test_4k_3840(self):
        assert self._file(3840, 2160).get_resolution() == "2160p"

    def test_4k_4096(self):
        assert self._file(4096, 2160).get_resolution() == "2160p"

    def test_576p(self):
        assert self._file(720, 576).get_resolution() == "576p"

    def test_480p(self):
        assert self._file(692, 480).get_resolution() == "480p"

    def test_interlaced(self):
        f = self._file(1920, 1080, scan_type="Interlaced")
        assert f.get_resolution() == "1080i"

    def test_progressive_not_interlaced(self):
        f = self._file(1920, 1080, scan_type="Progressive")
        assert f.get_resolution() == "1080p"

    def test_unknown_width_falls_back_to_height(self):
        # Width not in lookup table → falls through to height check
        f = self._file(999, 720)
        assert f.get_resolution() == "720p"

    def test_no_video_track(self):
        f = _make_media_file(media_info=_make_media_info())
        with pytest.raises(RuntimeError, match="No video track found"):
            f.get_resolution()


# ---------------------------------------------------------------------------
# get_video_codec
# ---------------------------------------------------------------------------

class TestGetVideoCodec:
    def _file(self, fmt, codec_id="", filename="test.mkv", encoding_settings=""):
        video = {"Format": fmt, "CodecID": codec_id, "Encoding_settings": encoding_settings}
        f = _make_media_file(filename=filename, media_info=_make_media_info(video=video))
        return f

    def test_av1(self):
        assert self._file("AV1").get_video_codec("WEB-DL") == "AV1"

    def test_x265_web(self):
        assert self._file("HEVC").get_video_codec("WEB-DL") == "x265"

    def test_hevc_remux(self):
        assert self._file("HEVC").get_video_codec("BluRay Remux") == "HEVC"

    def test_h265_filename(self):
        assert self._file("HEVC", filename="show.h265.mkv").get_video_codec("WEB-DL") == "H265"

    def test_avc_remux(self):
        assert self._file("AVC").get_video_codec("BluRay Remux") == "AVC"

    def test_x264_filename(self):
        assert self._file("AVC", filename="movie.x264.mkv").get_video_codec("WEB-DL") == "x264"

    def test_x264_encoding_settings(self):
        assert self._file("AVC", encoding_settings="cabac=1 / ref=3 / x264").get_video_codec("WEB-DL") == "x264"

    def test_h264_default(self):
        assert self._file("AVC").get_video_codec("WEB-DL") == "H264"

    def test_vc1(self):
        assert self._file("VC-1").get_video_codec("BluRay Remux") == "VC-1"

    def test_mpeg2(self):
        assert self._file("MPEG Video", codec_id="V_MPEG2").get_video_codec("DVD") == "MPEG-2"

    def test_no_video_track(self):
        f = _make_media_file(media_info=_make_media_info())
        with pytest.raises(RuntimeError, match="No video track found"):
            f.get_video_codec("WEB-DL")


# ---------------------------------------------------------------------------
# get_audio_info
# ---------------------------------------------------------------------------

class TestGetAudioInfo:
    def _file(self, audio: dict):
        return _make_media_file(media_info=_make_media_info(audio=audio))

    def test_truehd_atmos(self):
        audio = {
            "Format": "MLP FBA",
            "Format_Commercial_IfAny": "Dolby TrueHD with Dolby Atmos",
            "Channels": "8",
            "ChannelLayout": "L R C LFE Ls Rs Lh Rh",
        }
        result = self._file(audio).get_audio_info()
        assert result.startswith("TrueHD Atmos")

    def test_truehd(self):
        audio = {
            "Format": "MLP FBA",
            "Format_Commercial_IfAny": "Dolby TrueHD",
            "Channels": "6",
            "ChannelLayout": "L R C LFE Ls Rs",
        }
        result = self._file(audio).get_audio_info()
        assert result.startswith("TrueHD")
        assert "Atmos" not in result

    def test_ddp(self):
        audio = {
            "Format": "E-AC-3",
            "Format_Commercial_IfAny": "Dolby Digital Plus",
            "Channels": "6",
            "ChannelLayout": "L R C LFE Ls Rs",
        }
        result = self._file(audio).get_audio_info()
        assert result == "DDP 5.1"

    def test_dd(self):
        audio = {
            "Format": "AC-3",
            "Format_Commercial_IfAny": "Dolby Digital",
            "Channels": "6",
            "ChannelLayout": "L R C LFE Ls Rs",
        }
        result = self._file(audio).get_audio_info()
        assert result == "DD 5.1"

    def test_dts_hd_ma(self):
        audio = {
            "Format": "DTS",
            "Format_Commercial_IfAny": "DTS-HD Master Audio",
            "Channels": "8",
            "ChannelLayout": "L R C LFE Ls Rs Lss Rss",
        }
        result = self._file(audio).get_audio_info()
        assert result.startswith("DTS-HD MA")

    def test_aac_stereo(self):
        audio = {
            "Format": "AAC",
            "Channels": "2",
            "ChannelLayout": "L R",
        }
        result = self._file(audio).get_audio_info()
        assert result == "AAC 2.0"

    def test_no_audio_track(self):
        f = _make_media_file(media_info=_make_media_info())
        assert f.get_audio_info() == "NONE 0.0"


# ---------------------------------------------------------------------------
# get_colour_space
# ---------------------------------------------------------------------------

class TestGetColourSpace:
    def _file(self, video: dict):
        return _make_media_file(media_info=_make_media_info(video=video))

    def test_sdr(self):
        assert self._file({"Format": "AVC"}).get_colour_space() == "SDR"

    def test_hdr(self):
        assert self._file({"HDR_Format": "SMPTE ST 2086"}).get_colour_space() == "HDR"

    def test_hdr10plus(self):
        # MediaInfo reports HDR10+ in HDR_Format_Compatibility when combined with another layer,
        # or directly as "HDR10+" in HDR_Format for standalone HDR10+
        assert self._file({"HDR_Format": "HDR10+"}).get_colour_space() == "HDR10+"

    def test_dolby_vision_hdr10_compat(self):
        f = self._file({"HDR_Format": "Dolby Vision", "HDR_Format_Compatibility": "HDR10"})
        assert f.get_colour_space() == "DV HDR"

    def test_dolby_vision_hdr10plus_compat(self):
        f = self._file({"HDR_Format": "Dolby Vision", "HDR_Format_Compatibility": "HDR10+"})
        assert f.get_colour_space() == "DV HDR10+"

    def test_dolby_vision_no_compat(self):
        f = self._file({"HDR_Format": "Dolby Vision"})
        assert f.get_colour_space() == "DV"


# ---------------------------------------------------------------------------
# get_language_name
# ---------------------------------------------------------------------------

class TestGetLanguageName:
    def test_english(self):
        audio = {"Language": "en"}
        f = _make_media_file(media_info=_make_media_info(audio=audio))
        assert f.get_language_name() == "English"

    def test_no_language_raises(self):
        f = _make_media_file(media_info=_make_media_info(audio={"Format": "AAC"}))
        with pytest.raises(ValueError):
            f.get_language_name()

    def test_no_audio_track_raises(self):
        f = _make_media_file(media_info=_make_media_info())
        with pytest.raises(ValueError):
            f.get_language_name()

    def test_zxx_returns_none_string(self):
        audio = {"Language": "zxx"}
        f = _make_media_file(media_info=_make_media_info(audio=audio))
        assert f.get_language_name() == "NONE"

    def test_unknown_language_code_raises(self):
        audio = {"Language": "xyz-invalid"}
        f = _make_media_file(media_info=_make_media_info(audio=audio))
        with pytest.raises(ValueError):
            f.get_language_name()

    def test_two_primary_tracks_returns_dual(self):
        f = _make_media_file(media_info=_make_media_info(audio_tracks=[
            {"Language": "ja"},
            {"Language": "en"},
        ]))
        assert f.get_language_name() == "DUAL"

    def test_three_primary_tracks_returns_multi(self):
        f = _make_media_file(media_info=_make_media_info(audio_tracks=[
            {"Language": "ja"},
            {"Language": "en"},
            {"Language": "fr"},
        ]))
        assert f.get_language_name() == "MULTI"

    def test_commentary_tracks_excluded_from_count(self):
        # One real track + one commentary → still single language
        f = _make_media_file(media_info=_make_media_info(audio_tracks=[
            {"Language": "en"},
            {"Language": "en", "Title": "Director's Commentary"},
        ]))
        assert f.get_language_name() == "English"

    def test_commentary_excluded_leaving_two_primary(self):
        f = _make_media_file(media_info=_make_media_info(audio_tracks=[
            {"Language": "ja"},
            {"Language": "en"},
            {"Language": "en", "Title": "Commentary"},
        ]))
        assert f.get_language_name() == "DUAL"


# ---------------------------------------------------------------------------
# _filename_for_guessit  (AV1 stripping)
# ---------------------------------------------------------------------------

class TestFilenameForGuessit:
    """Unit tests for the AV1-stripping pre-processing applied before guessit."""

    def _av1_file(self, filename):
        video = {"Format": "AV1", "Width": "1920", "Height": "1080"}
        return _make_media_file(filename=filename, media_info=_make_media_info(video=video))

    def _hevc_file(self, filename):
        video = {"Format": "HEVC", "Width": "1920", "Height": "1080"}
        return _make_media_file(filename=filename, media_info=_make_media_info(video=video))

    def test_av1_before_hyphen_stripped(self):
        f = self._av1_file("Show.S01E01.1080p.WEB-DL.DDP5.1.AV1-GRP.mkv")
        assert f._filename_for_guessit() == "Show.S01E01.1080p.WEB-DL.DDP5.1-GRP.mkv"

    def test_av1_before_dot_stripped(self):
        f = self._av1_file("Show.S01E01.1080p.WEB-DL.DDP5.1.AV1.GRP.mkv")
        assert f._filename_for_guessit() == "Show.S01E01.1080p.WEB-DL.DDP5.1.GRP.mkv"

    def test_av1_case_insensitive(self):
        f = self._av1_file("Show.S01E01.1080p.WEB-DL.DDP5.1.av1-GRP.mkv")
        assert f._filename_for_guessit() == "Show.S01E01.1080p.WEB-DL.DDP5.1-GRP.mkv"

    def test_not_stripped_when_codec_is_not_av1(self):
        """AV1 in filename but MediaInfo reports HEVC — must not strip."""
        f = self._hevc_file("Show.S01E01.1080p.WEB-DL.DDP5.1.AV1-GRP.mkv")
        assert f._filename_for_guessit() == "Show.S01E01.1080p.WEB-DL.DDP5.1.AV1-GRP.mkv"

    def test_no_av1_in_filename_unchanged(self):
        f = self._av1_file("Show.S01E01.1080p.WEB-DL.x265-GRP.mkv")
        assert f._filename_for_guessit() == "Show.S01E01.1080p.WEB-DL.x265-GRP.mkv"

    def test_regression_one_piece(self):
        """Regression for the original reported filename."""
        f = self._av1_file("ONE.PIECE.S02E05.WAX.ON,.WAX.OFF.1080p.NF.WEB-DL.DDP5.1.AV1-DBMS.mkv")
        assert f._filename_for_guessit() == "ONE.PIECE.S02E05.WAX.ON,.WAX.OFF.1080p.NF.WEB-DL.DDP5.1-DBMS.mkv"


# ---------------------------------------------------------------------------
# AV1 guessit integration — real guessit called via __init__
# ---------------------------------------------------------------------------

def _make_av1_mediafile(filename):
    """Create a real MediaFile instance (mocked _parse_media_info) with AV1 video."""
    from torrent_utils.media import MediaFile
    video = {"Format": "AV1", "Width": "1920", "Height": "1080"}
    media_info = _make_media_info(video=video)
    with patch.object(MediaFile, "_parse_media_info", return_value=media_info):
        return MediaFile(filename)


class TestAV1GuessitIntegration:
    """End-to-end: verify guessit receives a clean filename and returns the correct release_group."""

    def test_release_group_is_clean(self):
        f = _make_av1_mediafile("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-DBMS.mkv")
        assert f.guessit_info.get("release_group") == "DBMS"

    def test_regression_one_piece(self):
        f = _make_av1_mediafile("ONE.PIECE.S02E05.WAX.ON,.WAX.OFF.1080p.NF.WEB-DL.DDP5.1.AV1-DBMS.mkv")
        assert f.guessit_info.get("release_group") == "DBMS"

    def test_av1_not_in_release_group(self):
        f = _make_av1_mediafile("Movie.2023.2160p.MA.WEB-DL.DDP5.1.AV1-GROUPNAME.mkv")
        assert "AV1" not in (f.guessit_info.get("release_group") or "")

    def test_video_codec_field_absent_from_guessit(self):
        """Confirm guessit 3.8 still does not detect AV1 as video_codec (documents the known gap)."""
        f = _make_av1_mediafile("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-GRP.mkv")
        assert f.guessit_info.get("video_codec") is None


# ---------------------------------------------------------------------------
# AV1 in generate_name output
# ---------------------------------------------------------------------------

def _make_av1_tvshow(filename):
    """Create a TVShow with AV1 video/DDP audio/English, mocked metadata and network calls."""
    from torrent_utils.media import TVShow
    video = {"Format": "AV1", "Width": "1920", "Height": "1080"}
    audio = {
        "Format": "E-AC-3",
        "Format_Commercial_IfAny": "Dolby Digital Plus",
        "Channels": "6",
        "ChannelLayout": "L R C LFE Ls Rs",
        "Language": "en",
    }
    media_info = _make_media_info(video=video, audio=audio)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "Test Show", "first_air_date": "2023-01-01"}
    with patch.object(TVShow, "_parse_media_info", return_value=media_info), \
         patch("torrent_utils.media.requests.get", return_value=mock_resp):
        return TVShow(filename, tmdb_api_key="fake", tmdb_id=12345)


class TestAV1GenerateName:
    """Tests that generate_name produces correct AV1 naming — codec present, not part of group."""

    def test_huno_format_codec_is_av1(self):
        f = _make_av1_tvshow("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-GRP.mkv")
        name = f.generate_name(source="NF WEB-DL", group="GRP", huno_format=True)
        assert "AV1" in name

    def test_huno_format_group_not_prefixed_with_av1(self):
        f = _make_av1_tvshow("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-GRP.mkv")
        name = f.generate_name(source="NF WEB-DL", group="GRP", huno_format=True)
        assert "- GRP)" in name
        assert "AV1-GRP" not in name

    def test_standard_format_codec_is_av1(self):
        f = _make_av1_tvshow("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-GRP.mkv")
        name = f.generate_name(source="NF WEB-DL", group="GRP", huno_format=False)
        assert "AV1" in name

    def test_huno_format_full_structure(self):
        """Regression: full expected name format for an AV1 episode."""
        f = _make_av1_tvshow("Show.S01E01.1080p.NF.WEB-DL.DDP5.1.AV1-GRP.mkv")
        name = f.generate_name(source="NF WEB-DL", group="GRP", huno_format=True)
        assert name == "Test Show (2023) S01E01 (1080p NF WEB-DL AV1 SDR DDP 5.1 English - GRP).mkv"
