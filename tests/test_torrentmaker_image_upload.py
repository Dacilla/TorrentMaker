"""Tests for torrentmaker.py screenshot upload host priority."""
from unittest.mock import patch


def test_upload_single_screenshot_uses_hawkepics_before_ptpimg(tmp_path):
    from torrentmaker import upload_single_screenshot

    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")

    with (
        patch("torrentmaker.upload_to_hawkepics", return_value="https://hawke.pics/image/abc.png") as hawke,
        patch("torrentmaker.uploadToPTPIMG", return_value="https://ptpimg.me/abc.png") as ptpimg,
    ):
        bbcode = upload_single_screenshot(
            str(img),
            hawkepics_api="hawke-key",
            imgbb_api=None,
            ptpimg_api="ptp-key",
            catbox_hash=None,
        )

    assert bbcode == "[url=https://hawke.pics/image/abc.png][img]https://hawke.pics/image/abc.png[/img][/url]"
    hawke.assert_called_once_with(str(img), "hawke-key")
    ptpimg.assert_not_called()


def test_upload_single_screenshot_falls_back_to_ptpimg_after_hawkepics_failure(tmp_path):
    from torrentmaker import upload_single_screenshot

    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")

    with (
        patch("torrentmaker.upload_to_hawkepics", return_value=None) as hawke,
        patch("torrentmaker.uploadToPTPIMG", return_value="https://ptpimg.me/abc.png") as ptpimg,
    ):
        bbcode = upload_single_screenshot(
            str(img),
            hawkepics_api="hawke-key",
            imgbb_api=None,
            ptpimg_api="ptp-key",
            catbox_hash=None,
        )

    assert bbcode == "[url=https://ptpimg.me/abc.png][img]https://ptpimg.me/abc.png[/img][/url]"
    hawke.assert_called_once_with(str(img), "hawke-key")
    ptpimg.assert_called_once_with(str(img), "ptp-key")
