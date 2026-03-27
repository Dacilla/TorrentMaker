"""Tests for torrent_utils/media.py — all external calls mocked."""
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers to build a minimal pymediainfo-style JSON structure
# ---------------------------------------------------------------------------

def _make_media_info(video: dict = None, audio: dict = None):
    """Return a fake media_info dict matching the pymediainfo JSON schema."""
    tracks = [{"@type": "General"}]
    if video:
        t = {"@type": "Video"}
        t.update(video)
        tracks.append(t)
    if audio:
        t = {"@type": "Audio"}
        t.update(audio)
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
        assert f.get_resolution() == "Unknown"


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
        assert f.get_video_codec("WEB-DL") == "H264"


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
        assert f.get_audio_info() == ""


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
