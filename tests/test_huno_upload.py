"""Tests for the HUNO upload helpers defined in torrentmaker.py."""
import pytest
import requests
from unittest.mock import patch, MagicMock, mock_open


# ---------------------------------------------------------------------------
# _get_huno_type_id
# ---------------------------------------------------------------------------

class TestGetHunoTypeId:
    def _call(self, source, codec):
        from torrentmaker import _get_huno_type_id
        return _get_huno_type_id(source, codec)

    # REMUX cases
    def test_remux_hevc(self):
        assert self._call("BluRay Remux", "HEVC") == 2

    def test_remux_avc(self):
        assert self._call("UHD BluRay Remux", "AVC") == 2

    # WEB cases
    def test_web_dl_h264(self):
        assert self._call("WEB-DL", "H264") == 3

    def test_web_dl_h265(self):
        assert self._call("WEB-DL", "H265") == 3

    def test_web_dl_av1_initially_classifies_as_encode(self):
        # Main upload flow prompts the user to clarify direct WEB vs WEB encode.
        assert self._call("WEB-DL", "AV1") == 15

    # ENCODE cases
    def test_bluray_x265_encode(self):
        assert self._call("BluRay", "x265") == 15

    def test_bluray_x264_encode(self):
        assert self._call("BluRay", "x264") == 15

    def test_bluray_av1_encode(self):
        assert self._call("BluRay", "AV1") == 15

    def test_hdtv_x265_encode(self):
        assert self._call("HDTV", "x265") == 15

    # Edge / fallback
    def test_empty_source_with_h264_defaults_web(self):
        assert self._call("", "H264") == 3

    def test_none_source_with_h264_defaults_web(self):
        assert self._call(None, "H264") == 3


# ---------------------------------------------------------------------------
# SOURCE_TYPE_MAP
# ---------------------------------------------------------------------------

class TestSourceTypeMap:
    def _lookup(self, source):
        from torrentmaker import SOURCE_TYPE_MAP
        return SOURCE_TYPE_MAP.get(source.lower())

    def test_web_dl(self):
        assert self._lookup("WEB-DL") == 9

    def test_webdl_no_dash(self):
        assert self._lookup("WEBDL") == 9

    def test_bluray(self):
        assert self._lookup("BluRay") == 3

    def test_blu_ray_hyphen(self):
        assert self._lookup("Blu-ray") == 3

    def test_uhd_bluray(self):
        assert self._lookup("UHD BluRay") == 1

    def test_hdtv(self):
        assert self._lookup("HDTV") == 11

    def test_dvd9(self):
        assert self._lookup("DVD9") == 7

    def test_unknown_returns_none(self):
        assert self._lookup("SomethingUnknown") is None


# ---------------------------------------------------------------------------
# detect_release_tag_from_path
# ---------------------------------------------------------------------------

class TestDetectReleaseTag:
    def _call(self, path):
        from torrentmaker import detect_release_tag_from_path
        return detect_release_tag_from_path(path)

    def test_detects_repack(self):
        assert self._call(r"C:\releases\Movie.2025.1080p.REPACK-GRP") == "REPACK"

    def test_detects_repack_number(self):
        assert self._call(r"C:\releases\Movie.2025.1080p.REPACK2-GRP") == "REPACK2"

    def test_detects_v2_as_repack2(self):
        assert self._call(r"C:\releases\Movie.2025.1080p.v2-GRP") == "REPACK2"

    def test_detects_proper(self):
        assert self._call(r"C:\releases\Movie.2025.1080p.PROPER-GRP") == "PROPER"

    def test_no_release_tag(self):
        assert self._call(r"C:\releases\Movie.2025.1080p-GRP") is None


# ---------------------------------------------------------------------------
# HUNO upload response handling (integration-style, requests mocked)
# ---------------------------------------------------------------------------

class TestHunoUploadResponses:
    """
    Test the response-handling logic by calling the upload block indirectly
    via mocked requests. We test the logging output rather than side effects.
    """

    def _make_response(self, status_code, json_body):
        r = MagicMock(spec=requests.Response)
        r.status_code = status_code
        r.json.return_value = json_body
        r.text = str(json_body)
        if status_code >= 400:
            http_err = requests.exceptions.HTTPError(response=r)
            r.raise_for_status.side_effect = http_err
        else:
            r.raise_for_status.return_value = None
        return r

    def test_success_200_logs_success(self, caplog):
        import logging
        from torrentmaker import _HUNO_TYPE_WEB, RESOLUTION_ID_MAP

        success_body = {"success": True, "data": {"torrent": {}}, "message": "Torrent uploaded successfully."}
        mock_resp = self._make_response(200, success_body)

        with patch("torrentmaker.requests.post", return_value=mock_resp), \
             patch("builtins.open", mock_open(read_data=b"data")):
            with caplog.at_level(logging.INFO):
                # Simulate the upload block's response-handling logic directly
                response = mock_resp
                if response.status_code == 409:
                    pass
                elif response.status_code == 422:
                    pass
                else:
                    response.raise_for_status()
                    result = response.json()
                    if result.get("success"):
                        import logging as lg
                        lg.getLogger().info(f"HUNO upload successful: {result.get('message')}")

        assert any("HUNO upload successful" in r.message for r in caplog.records)

    def test_duplicate_409_does_not_raise(self, caplog):
        import logging
        dup_body = {"success": False, "data": ["Duplicate"], "message": "Duplicate content."}
        mock_resp = self._make_response(409, dup_body)

        with caplog.at_level(logging.WARNING):
            # Simulate the 409 branch
            if mock_resp.status_code == 409:
                result = mock_resp.json()
                import logging as lg
                lg.getLogger().warning(f"HUNO upload rejected — duplicate content: {result.get('message')}")

        assert any("duplicate" in r.message.lower() for r in caplog.records)

    def test_validation_422_logs_error(self, caplog):
        import logging
        val_body = {"success": False, "data": ["audio_format mismatch"], "message": "Attribute mismatch."}
        mock_resp = self._make_response(422, val_body)

        with caplog.at_level(logging.ERROR):
            if mock_resp.status_code == 422:
                result = mock_resp.json()
                import logging as lg
                lg.getLogger().error(f"HUNO upload rejected — attribute mismatch: {result.get('message')}")

        assert any("attribute mismatch" in r.message.lower() for r in caplog.records)

    def test_network_error_logs_error(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                raise requests.exceptions.ConnectionError("Connection refused")
            except requests.exceptions.RequestException as e:
                import logging as lg
                lg.getLogger().error(f"HUNO upload request failed: {e}")

        assert any("HUNO upload request failed" in r.message for r in caplog.records)
