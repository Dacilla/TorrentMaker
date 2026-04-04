#!/usr/bin/env python3
"""
Diagnostic probe for slow.pics endpoint behavior.

Usage:
    python .\\slowpics_probe.py
"""

import os
import sys
import tempfile
from urllib.parse import unquote
import uuid

import requests
from PIL import Image


def _print_response(label, response):
    print(f"\n[{label}]")
    print(f"status: {response.status_code}")
    print(f"content-type: {response.headers.get('content-type')}")
    print(f"server: {response.headers.get('server')}")
    print(f"cf-ray: {response.headers.get('cf-ray')}")
    snippet = (response.text or "").strip().replace("\n", " ")[:400]
    print(f"body: {snippet!r}")


def _create_png(path, color):
    Image.new("RGB", (96, 96), color=color).save(path)


def main():
    with requests.Session() as session:
        r = session.get("https://slow.pics/comparison", timeout=30)
        _print_response("GET /comparison", r)
        r.raise_for_status()

        try:
            r_api = session.get("https://slow.pics/api/comparison", timeout=30)
            _print_response("GET /api/comparison", r_api)
        except requests.RequestException as exc:
            print(f"\n[GET /api/comparison] failed: {exc}")

        xsrf = session.cookies.get("XSRF-TOKEN")
        print(f"\nXSRF cookie present: {bool(xsrf)}")
        if not xsrf:
            print("No XSRF token cookie found; aborting.")
            return 1
        xsrf = unquote(xsrf)

        browser_id = str(uuid.uuid4())
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://slow.pics",
            "Referer": "https://slow.pics/comparison",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-XSRF-TOKEN": xsrf,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
                "Gecko/20100101 Firefox/149.0"
            ),
        }
        session.cookies.set("BROWSER-ID", browser_id, domain="slow.pics", path="/")

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.png")
            enc = os.path.join(td, "enc.png")
            _create_png(src, "blue")
            _create_png(enc, "green")

            with open(src, "rb") as src_f, open(enc, "rb") as enc_f:
                data_upload = {
                    "collectionName": "slowpics probe upload endpoint",
                    "browserId": browser_id,
                    "optimizeImages": "true",
                    "desiredFileType": "image/webp",
                    "hentai": "false",
                    "public": "true",
                    "visibility": "PUBLIC",
                    "removeAfter": "",
                    "canvasMode": "none",
                    "imageFit": "none",
                    "imagePosition": "center",
                    "comparisons[0].name": "00",
                    "comparisons[0].hentai": "false",
                    "comparisons[0].sortOrder": "0",
                    "comparisons[0].images[0].name": "source",
                    "comparisons[0].images[0].sortOrder": "0",
                    "comparisons[0].images[1].name": "encode",
                    "comparisons[0].images[1].sortOrder": "1",
                }
                files_upload = [
                    ("comparisons[0].images[0].file", ("src.png", src_f, "image/png")),
                    ("comparisons[0].images[1].file", ("enc.png", enc_f, "image/png")),
                ]
                r_upload = session.post(
                    "https://slow.pics/upload/comparison",
                    headers=headers,
                    data=data_upload,
                    files=files_upload,
                    timeout=120,
                )
                _print_response("POST /upload/comparison", r_upload)

            with open(src, "rb") as src_f, open(enc, "rb") as enc_f:
                data_api = {
                    "collectionName": "slowpics probe api endpoint",
                    "public": "false",
                    "optimize-images": "true",
                    "browserId": browser_id,
                    "comparisons[0].name": "001",
                    "comparisons[0].images[0].name": "Source",
                    "comparisons[0].images[1].name": "Encode",
                }
                files_api = [
                    ("comparisons[0].images[0].file", ("src.png", src_f, "image/png")),
                    ("comparisons[0].images[1].file", ("enc.png", enc_f, "image/png")),
                ]
                r_api_post = session.post(
                    "https://slow.pics/api/comparison",
                    headers=headers,
                    data=data_api,
                    files=files_api,
                    timeout=120,
                )
                _print_response("POST /api/comparison", r_api_post)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
