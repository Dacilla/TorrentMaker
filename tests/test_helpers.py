"""Tests for torrent_utils/helpers.py — all I/O and network calls mocked."""
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# is_valid_torf_hash
# ---------------------------------------------------------------------------

class TestIsValidTorfHash:
    from torrent_utils.helpers import is_valid_torf_hash

    def test_valid_40char_hex(self):
        from torrent_utils.helpers import is_valid_torf_hash
        assert is_valid_torf_hash("a" * 40) is True

    def test_valid_80char_hex(self):
        from torrent_utils.helpers import is_valid_torf_hash
        assert is_valid_torf_hash("b" * 80) is True

    def test_invalid_length(self):
        from torrent_utils.helpers import is_valid_torf_hash
        assert is_valid_torf_hash("a" * 39) is False

    def test_not_hex(self):
        from torrent_utils.helpers import is_valid_torf_hash
        assert is_valid_torf_hash("g" * 40) is False

    def test_none(self):
        from torrent_utils.helpers import is_valid_torf_hash
        assert is_valid_torf_hash(None) is False

    def test_empty_string(self):
        from torrent_utils.helpers import is_valid_torf_hash
        # Empty string: bytes.fromhex("") = b"", len=0, 0 % 20 == 0 → True
        assert is_valid_torf_hash("") is True


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical(self):
        from torrent_utils.helpers import similarity
        assert similarity("hello", "hello") == 100.0

    def test_completely_different(self):
        from torrent_utils.helpers import similarity
        score = similarity("abc", "xyz")
        assert score < 50.0

    def test_empty_strings(self):
        from torrent_utils.helpers import similarity
        assert similarity("", "") == 100.0

    def test_partial_match(self):
        from torrent_utils.helpers import similarity
        score = similarity("The Dark Knight", "The Dark Knight Rises")
        assert 50.0 < score < 100.0


# ---------------------------------------------------------------------------
# get_season / get_episode
# ---------------------------------------------------------------------------

class TestGetSeason:
    def test_standard_s03(self):
        from torrent_utils.helpers import get_season
        assert get_season("Show.S03E01.mkv") == "S03"

    def test_single_digit_padded(self):
        from torrent_utils.helpers import get_season
        assert get_season("Show.S1E01.mkv") == "S01"

    def test_not_found_raises(self):
        from torrent_utils.helpers import get_season
        with pytest.raises(ValueError):
            get_season("show_no_season_info.mkv")


class TestGetEpisode:
    def test_standard_e01(self):
        from torrent_utils.helpers import get_episode
        assert get_episode("Show.S03E01.mkv") == "01"

    def test_episode_12(self):
        from torrent_utils.helpers import get_episode
        assert get_episode("Show.S01E12.mkv") == "12"

    def test_not_found_raises(self):
        from torrent_utils.helpers import get_episode
        with pytest.raises(ValueError):
            get_episode("show_no_episode_info.mkv")


# ---------------------------------------------------------------------------
# get_path_list
# ---------------------------------------------------------------------------

class TestGetPathList:
    def test_cli_arg_returns_list(self):
        from torrent_utils.helpers import get_path_list
        result = get_path_list("/some/path/to/file.mkv", "bulkProcess.txt")
        assert result == ["/some/path/to/file.mkv"]

    def test_bulk_file_returns_sorted_list(self, tmp_path):
        from torrent_utils.helpers import get_path_list
        bulk = tmp_path / "bulkProcess.txt"
        bulk.write_text("/path/b\n/path/a\n", encoding="utf-8")
        result = get_path_list(None, str(bulk))
        assert result == sorted(["/path/b", "/path/a"])

    def test_missing_bulk_file_returns_empty(self, tmp_path):
        from torrent_utils.helpers import get_path_list
        result = get_path_list(None, str(tmp_path / "nonexistent.txt"))
        assert result == []


# ---------------------------------------------------------------------------
# FileOrFolder
# ---------------------------------------------------------------------------

class TestFileOrFolder:
    def test_file(self, tmp_path):
        from torrent_utils.helpers import FileOrFolder
        f = tmp_path / "test.mkv"
        f.write_bytes(b"")
        assert FileOrFolder(str(f)) == 1

    def test_folder(self, tmp_path):
        from torrent_utils.helpers import FileOrFolder
        assert FileOrFolder(str(tmp_path)) == 2

    def test_missing(self, tmp_path):
        from torrent_utils.helpers import FileOrFolder
        assert FileOrFolder(str(tmp_path / "nonexistent")) == 0


# ---------------------------------------------------------------------------
# uploadToPTPIMG
# ---------------------------------------------------------------------------

class TestUploadToPTPIMG:
    def _mock_response(self, json_data=None, status_code=200, raise_for_status=None):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data
        if raise_for_status:
            mock.raise_for_status.side_effect = raise_for_status
        else:
            mock.raise_for_status.return_value = None
        return mock

    def test_success(self, tmp_path):
        from torrent_utils.helpers import uploadToPTPIMG
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = self._mock_response(json_data=[{"code": "abc123", "ext": "png"}])
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url = uploadToPTPIMG(str(img), "testapikey")
        assert url == "https://ptpimg.me/abc123.png"

    def test_http_error_returns_none(self, tmp_path):
        from torrent_utils.helpers import uploadToPTPIMG
        import requests as req
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = self._mock_response(
            status_code=403,
            raise_for_status=req.exceptions.HTTPError("403"),
        )
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            assert uploadToPTPIMG(str(img), "badkey") is None

    def test_bad_json_returns_none(self, tmp_path):
        from torrent_utils.helpers import uploadToPTPIMG
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        # Empty list causes IndexError on response_data[0], which is caught
        mock_resp = self._mock_response(json_data=[])
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            assert uploadToPTPIMG(str(img), "key") is None


# ---------------------------------------------------------------------------
# upload_to_imgbb
# ---------------------------------------------------------------------------

class TestUploadToImgbb:
    def test_success(self, tmp_path):
        from torrent_utils.helpers import upload_to_imgbb
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {"url": "https://i.ibb.co/img.png", "url_viewer": "https://ibb.co/img"}
        }
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url, viewer = upload_to_imgbb(str(img), "apikey")
        assert url == "https://i.ibb.co/img.png"
        assert viewer == "https://ibb.co/img"

    def test_http_error_returns_none_tuple(self, tmp_path):
        from torrent_utils.helpers import upload_to_imgbb
        import requests as req
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("500")
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url, viewer = upload_to_imgbb(str(img), "key")
        assert url is None and viewer is None


# ---------------------------------------------------------------------------
# upload_to_catbox
# ---------------------------------------------------------------------------

class TestUploadToCatbox:
    def test_success(self, tmp_path):
        from torrent_utils.helpers import upload_to_catbox
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = "https://files.catbox.moe/abc123.png"
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            result = upload_to_catbox(str(img))
        assert "catbox.moe" in result

    def test_no_catbox_in_response_returns_none(self, tmp_path):
        from torrent_utils.helpers import upload_to_catbox
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = "error: file too large"
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            assert upload_to_catbox(str(img)) is None


# ---------------------------------------------------------------------------
# upload_to_onlyimage
# ---------------------------------------------------------------------------

class TestUploadToOnlyimage:
    def test_success(self, tmp_path):
        from torrent_utils.helpers import upload_to_onlyimage
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status_code": 200,
            "image": {"url": "https://onlyimage.org/image/abc123.png"}
        }
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url = upload_to_onlyimage(str(img), "apikey")
        assert url == "https://onlyimage.org/image/abc123.png"

    def test_http_error_returns_none(self, tmp_path):
        from torrent_utils.helpers import upload_to_onlyimage
        import requests as req
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("401")
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url = upload_to_onlyimage(str(img), "badkey")
        assert url is None

    def test_bad_status_code_returns_none(self, tmp_path):
        from torrent_utils.helpers import upload_to_onlyimage
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status_code": 400,
            "error": {"message": "Invalid API key"}
        }
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url = upload_to_onlyimage(str(img), "badkey")
        assert url is None

    def test_bad_json_returns_none(self, tmp_path):
        from torrent_utils.helpers import upload_to_onlyimage
        import json
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        with patch("torrent_utils.helpers.requests.post", return_value=mock_resp):
            url = upload_to_onlyimage(str(img), "key")
        assert url is None
