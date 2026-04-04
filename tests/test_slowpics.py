#!/usr/bin/env python3
"""
Test script for slow.pics upload functionality.

Creates small test PNG images and uploads them to slow.pics to verify
the upload_to_slowpics function works correctly.
"""

import os
import sys
import logging
import tempfile
from pathlib import Path

# Add parent directory to path so we can import torrent_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Import the function to test
from torrent_utils.helpers import upload_to_slowpics


def create_test_image(width=100, height=100):
    """Create a simple PNG test image using PIL."""
    try:
        from PIL import Image
        # Create a simple colored image
        img = Image.new('RGB', (width, height), color='red')
        return img
    except ImportError:
        logging.error("PIL/Pillow not installed. Install with: pip install Pillow")
        raise


def test_slowpics_upload():
    """Test the slow.pics upload with dummy images."""

    logging.info("Starting slow.pics upload test...")

    # Create temporary directory for test images
    with tempfile.TemporaryDirectory() as tmpdir:
        logging.info(f"Using temp directory: {tmpdir}")

        # Create test images
        logging.info("Creating test images...")

        # Source image (blue)
        src_img = create_test_image()
        src_path = os.path.join(tmpdir, "source_00.png")
        src_img.save(src_path)
        logging.info(f"Created source image: {src_path}")

        # Encode image (green)
        enc_img = create_test_image()
        enc_img.paste((0, 255, 0), (0, 0, 100, 100))  # Green overlay
        enc_path = os.path.join(tmpdir, "encode_00.png")
        enc_img.save(enc_path)
        logging.info(f"Created encode image: {enc_path}")

        # Test upload with 1 frame pair
        image_pairs = [(src_path, enc_path)]
        collection_name = "Test Comparison - slow.pics Upload Test"
        labels = ["Source", "Encode"]
        hdr_type = "SDR"

        logging.info(f"Uploading to slow.pics...")
        logging.info(f"  Collection name: {collection_name}")
        logging.info(f"  Number of pairs: {len(image_pairs)}")
        logging.info(f"  Labels: {labels}")
        logging.info(f"  HDR type: {hdr_type}")

        remember_me = os.getenv("SLOWPICS_REMEMBER_ME") or None
        session_cookie = os.getenv("SLOWPICS_SESSION") or None

        result = upload_to_slowpics(
            image_pairs=image_pairs,
            collection_name=collection_name,
            labels=labels,
            hdr_type=hdr_type,
            remember_me=remember_me,
            session_cookie=session_cookie,
            return_status=True,
        )
        url = result.get("url")

        if url:
            logging.info(f"✓ Upload successful!")
            logging.info(f"✓ Comparison URL: {url}")
            print(f"\n{'='*60}")
            print(f"TEST PASSED - slow.pics upload works!")
            print(f"URL: {url}")
            print(f"{'='*60}\n")
            return True
        else:
            if result.get("error_code"):
                logging.error(f"slow.pics error: {result.get('error_code')} | {result.get('error_message')}")
            logging.error("✗ Upload failed or returned no URL")
            print(f"\n{'='*60}")
            print(f"TEST FAILED - slow.pics returned no URL")
            print(f"Check logs above for details")
            print(f"{'='*60}\n")
            return False


def test_slowpics_upload_multiple_frames():
    """Test slow.pics upload with multiple frame pairs."""

    logging.info("Starting multi-frame slow.pics upload test...")

    with tempfile.TemporaryDirectory() as tmpdir:
        logging.info(f"Using temp directory: {tmpdir}")

        # Create multiple test image pairs (3 frames)
        image_pairs = []
        for frame_num in range(3):
            # Source image
            src_img = create_test_image()
            src_path = os.path.join(tmpdir, f"source_{frame_num:02d}.png")
            src_img.save(src_path)

            # Encode image
            enc_img = create_test_image()
            enc_img.paste((0, 255, 0), (0, 0, 100, 100))
            enc_path = os.path.join(tmpdir, f"encode_{frame_num:02d}.png")
            enc_img.save(enc_path)

            image_pairs.append((src_path, enc_path))
            logging.info(f"Created frame pair {frame_num}: {src_path} + {enc_path}")

        collection_name = "Multi-Frame Test - slow.pics Upload Test"

        logging.info(f"Uploading {len(image_pairs)} frame pairs to slow.pics...")

        remember_me = os.getenv("SLOWPICS_REMEMBER_ME") or None
        session_cookie = os.getenv("SLOWPICS_SESSION") or None

        result = upload_to_slowpics(
            image_pairs=image_pairs,
            collection_name=collection_name,
            labels=["Source", "Encode"],
            hdr_type="SDR",
            remember_me=remember_me,
            session_cookie=session_cookie,
            return_status=True,
        )
        url = result.get("url")

        if url:
            logging.info(f"✓ Multi-frame upload successful!")
            logging.info(f"✓ Comparison URL: {url}")
            print(f"\n{'='*60}")
            print(f"TEST PASSED - multi-frame slow.pics upload works!")
            print(f"URL: {url}")
            print(f"{'='*60}\n")
            return True
        else:
            if result.get("error_code"):
                logging.error(f"slow.pics error: {result.get('error_code')} | {result.get('error_message')}")
            logging.error("✗ Multi-frame upload failed")
            print(f"\n{'='*60}")
            print(f"TEST FAILED - multi-frame upload failed")
            print(f"{'='*60}\n")
            return False


if __name__ == "__main__":
    import sys

    try:
        print("\n" + "="*60)
        print("slow.pics Upload Test Suite")
        print("="*60 + "\n")

        # Test 1: Single frame
        test1_pass = test_slowpics_upload()

        # Test 2: Multiple frames
        test2_pass = test_slowpics_upload_multiple_frames()

        # Summary
        print("\n" + "="*60)
        if test1_pass and test2_pass:
            print("ALL TESTS PASSED ✓")
            sys.exit(0)
        else:
            print("SOME TESTS FAILED ✗")
            sys.exit(1)
        print("="*60 + "\n")

    except Exception as e:
        logging.exception(f"Test suite failed with exception: {e}")
        print(f"\n{'='*60}")
        print(f"TEST SUITE CRASHED: {e}")
        print(f"{'='*60}\n")
        sys.exit(1)
