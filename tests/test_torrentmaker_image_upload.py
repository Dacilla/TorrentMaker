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


def test_extract_screenshot_bbcodes_uses_screens_section(tmp_path):
    from torrentmaker import extract_screenshot_bbcodes

    desc = tmp_path / "showDesc.txt"
    desc.write_text(
        "[color=#ffffff][center][b]Comparison[/b][/center][/color]\n"
        "[center][url=https://example.test/source.png][img]https://example.test/source.png[/img][/url][/center]\n"
        "[color=#ffffff][center][b]Screens[/b][/center][/color]\n"
        "[center][url=https://example.test/screen1.png][img]https://example.test/screen1.png[/img][/url][/center]\n"
        "[center][url=https://example.test/screen2.png][img]https://example.test/screen2.png[/img][/url][/center]\n",
        encoding="utf-8",
    )

    assert extract_screenshot_bbcodes(str(desc)) == [
        "[url=https://example.test/screen1.png][img]https://example.test/screen1.png[/img][/url]",
        "[url=https://example.test/screen2.png][img]https://example.test/screen2.png[/img][/url]",
    ]
