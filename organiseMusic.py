from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import APIC


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".flac"}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
COMMON_COVER_FILENAMES = {
    "cover",
    "folder",
    "front",
    "album",
    "artwork",
    "albumart",
}


@dataclass
class TrackInfo:
    source_path: Path
    extension: str
    artist: str
    album: str
    year: str
    title: str
    track_number: int
    disc_number: Optional[int]
    total_discs: Optional[int]
    container: str
    quality: str


def clean_component(value: str, fallback: str) -> str:
    value = (value or "").strip()
    if not value:
        value = fallback

    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = value.rstrip(" .")
    return value or fallback


def strip_audio_extension_from_title(title: str) -> str:
    title = (title or "").strip()
    return re.sub(r"\.(mp3|flac|m4a|aac|wav|ogg)$", "", title, flags=re.IGNORECASE).strip()


def first_tag(tags, *keys: str) -> Optional[str]:
    for key in keys:
        value = tags.get(key)
        if value is None:
            continue

        if isinstance(value, list):
            if not value:
                continue
            value = value[0]

        text = str(value).strip()
        if text:
            return text

    return None


def parse_number_field(value: Optional[str]) -> Optional[int]:
    if not value:
        return None

    match = re.match(r"^\s*(\d+)", str(value).strip())
    if match:
        return int(match.group(1))
    return None


def parse_disc_field(value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not value:
        return None, None

    match = re.match(r"^\s*(\d+)(?:\s*/\s*(\d+))?", str(value).strip())
    if not match:
        return None, None

    disc_number = int(match.group(1))
    total_discs = int(match.group(2)) if match.group(2) else None
    return disc_number, total_discs


def infer_year(date_str: Optional[str]) -> str:
    if not date_str:
        return "Unknown Year"

    match = re.search(r"(\d{4})", str(date_str))
    if match:
        return match.group(1)

    return "Unknown Year"


def format_sample_rate(sample_rate: int) -> str:
    if not sample_rate:
        return "?"
    khz = sample_rate / 1000
    return f"{khz:g}"


def read_track_info(path: Path) -> Optional[TrackInfo]:
    try:
        audio = MutagenFile(path, easy=False)
    except Exception as exc:
        print(f"Skipping unreadable file: {path} ({exc})", file=sys.stderr)
        return None

    if audio is None:
        print(f"Skipping unsupported or unreadable file: {path}", file=sys.stderr)
        return None

    ext = path.suffix.lower().lstrip(".")
    tags = audio.tags or {}

    if isinstance(audio, MP3):
        artist = first_tag(tags, "TPE2", "TPE1")
        album = first_tag(tags, "TALB")
        title = first_tag(tags, "TIT2")
        date_value = first_tag(tags, "TDRC", "TYER")
        track_raw = first_tag(tags, "TRCK")
        disc_raw = first_tag(tags, "TPOS")

        bitrate = getattr(audio.info, "bitrate", 0)
        bitrate_kbps = int(round(bitrate / 1000)) if bitrate else 0

        quality = str(bitrate_kbps) if bitrate_kbps else "Unknown"
        container = "MP3"

    elif isinstance(audio, FLAC):
        artist = first_tag(tags, "albumartist", "artist")
        album = first_tag(tags, "album")
        title = first_tag(tags, "title")
        date_value = first_tag(tags, "date", "year")
        track_raw = first_tag(tags, "tracknumber")
        disc_raw = first_tag(tags, "discnumber")

        bits = getattr(audio.info, "bits_per_sample", 0) or 0
        sample_rate = getattr(audio.info, "sample_rate", 0) or 0

        quality = f"{bits if bits else '?'}B-{format_sample_rate(sample_rate)}KHz"
        container = "FLAC"

    else:
        print(f"Skipping unsupported file type: {path}", file=sys.stderr)
        return None

    disc_number, total_discs = parse_disc_field(disc_raw)

    artist = clean_component(artist or path.parent.name, "Unknown Artist")
    album = clean_component(album or path.parent.name, "Unknown Album")
    title = strip_audio_extension_from_title(title or path.stem)
    title = clean_component(title, path.stem)
    year = clean_component(infer_year(date_value), "Unknown Year")
    track_number = parse_number_field(track_raw) or 0

    return TrackInfo(
        source_path=path,
        extension=ext,
        artist=artist,
        album=album,
        year=year,
        title=title,
        track_number=track_number,
        disc_number=disc_number,
        total_discs=total_discs,
        container=container,
        quality=quality,
    )


def build_destination(root: Path, info: TrackInfo) -> Path:
    album_folder = f"{info.album} ({info.year}) [{info.container}] [{info.quality}]"
    parts: list[Path] = [root, Path(info.artist), Path(album_folder)]

    if info.total_discs and info.total_discs > 1:
        parts.append(Path(f"CD{info.disc_number or 1}"))
    elif info.disc_number and info.disc_number > 1:
        parts.append(Path(f"CD{info.disc_number}"))

    filename = f"{info.track_number:02d}. {info.title}.{info.extension}"
    dest_dir = Path(*parts)
    return dest_dir / filename


def same_file(src: Path, dst: Path) -> bool:
    try:
        return src.resolve() == dst.resolve()
    except Exception:
        return False


def uniquify_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def find_external_cover(source_dir: Path) -> Optional[Path]:
    candidates: list[Path] = []

    for item in source_dir.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue

        stem_lower = item.stem.lower()
        if stem_lower in COMMON_COVER_FILENAMES:
            candidates.append(item)

    if candidates:
        candidates.sort(key=lambda p: (p.stem.lower(), p.suffix.lower()))
        return candidates[0]

    # Fallback: if there is exactly one image in the folder, treat it as cover art
    images = [
        item for item in source_dir.iterdir()
        if item.is_file() and item.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    if len(images) == 1:
        return images[0]

    return None


def embedded_cover_bytes_and_ext(audio_path: Path) -> tuple[Optional[bytes], Optional[str]]:
    try:
        audio = MutagenFile(audio_path, easy=False)
    except Exception:
        return None, None

    if audio is None:
        return None, None

    if isinstance(audio, MP3):
        tags = audio.tags
        if tags:
            for tag in tags.values():
                if isinstance(tag, APIC) and getattr(tag, "data", None):
                    mime = (tag.mime or "").lower()
                    if "png" in mime:
                        return tag.data, ".png"
                    return tag.data, ".jpg"

    elif isinstance(audio, FLAC):
        pictures = getattr(audio, "pictures", []) or []
        for pic in pictures:
            if isinstance(pic, Picture) and getattr(pic, "data", None):
                mime = (pic.mime or "").lower()
                if "png" in mime:
                    return pic.data, ".png"
                return pic.data, ".jpg"

    return None, None


def album_root_from_destination(dest_audio_path: Path) -> Path:
    if dest_audio_path.parent.name.startswith("CD"):
        return dest_audio_path.parent.parent
    return dest_audio_path.parent


def ensure_album_cover(
    source_audio_path: Path,
    destination_audio_path: Path,
    dry_run: bool,
    copy_only: bool,
) -> None:
    album_dir = album_root_from_destination(destination_audio_path)
    existing_covers = [
        p for p in album_dir.iterdir()
        if p.is_file() and p.stem.lower() in COMMON_COVER_FILENAMES and p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ] if album_dir.exists() else []

    if existing_covers:
        return

    source_dir = source_audio_path.parent
    external_cover = None
    try:
        external_cover = find_external_cover(source_dir)
    except Exception:
        external_cover = None

    if external_cover is not None:
        dest_cover = album_dir / f"cover{external_cover.suffix.lower()}"
        dest_cover = uniquify_path(dest_cover) if dest_cover.exists() else dest_cover

        print(f"  cover: {external_cover} -> {dest_cover}")
        if dry_run:
            return

        album_dir.mkdir(parents=True, exist_ok=True)
        try:
            if copy_only:
                shutil.copy2(external_cover, dest_cover)
            else:
                if not same_file(external_cover, dest_cover):
                    shutil.move(str(external_cover), str(dest_cover))
        except Exception as exc:
            print(f"Failed to process cover image {external_cover}: {exc}", file=sys.stderr)
        return

    image_bytes, ext = embedded_cover_bytes_and_ext(source_audio_path)
    if image_bytes and ext:
        dest_cover = album_dir / f"cover{ext}"
        if dest_cover.exists():
            return

        print(f"  embedded cover -> {dest_cover}")
        if dry_run:
            return

        album_dir.mkdir(parents=True, exist_ok=True)
        try:
            dest_cover.write_bytes(image_bytes)
        except Exception as exc:
            print(f"Failed to write embedded cover for {source_audio_path}: {exc}", file=sys.stderr)


def cleanup_empty_dirs(root: Path) -> None:
    all_dirs = sorted(
        [p for p in root.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for directory in all_dirs:
        try:
            next(directory.iterdir())
        except StopIteration:
            try:
                directory.rmdir()
            except OSError:
                pass
        except OSError:
            pass


def organise_music(root: Path, dry_run: bool, copy_only: bool, remove_empty_dirs: bool) -> None:
    files = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]

    if not files:
        print("No supported music files found.")
        return

    print(f"Found {len(files)} music files.\n")

    moved_destinations: list[Path] = []

    for source in files:
        info = read_track_info(source)
        if info is None:
            continue

        destination = build_destination(root, info)
        final_destination = destination if not destination.exists() else uniquify_path(destination)

        if same_file(source, final_destination):
            print(f"Already organised: {source}")
            moved_destinations.append(final_destination)
            continue

        print(f"{source} -> {final_destination}")

        if not dry_run:
            final_destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                if copy_only:
                    shutil.copy2(source, final_destination)
                else:
                    shutil.move(str(source), str(final_destination))
            except Exception as exc:
                print(f"Failed to process {source}: {exc}", file=sys.stderr)
                continue

        moved_destinations.append(final_destination)

        try:
            ensure_album_cover(
                source_audio_path=source,
                destination_audio_path=final_destination,
                dry_run=dry_run,
                copy_only=copy_only,
            )
        except Exception as exc:
            print(f"Failed while handling cover art for {source}: {exc}", file=sys.stderr)

    if remove_empty_dirs and not dry_run and not copy_only:
        cleanup_empty_dirs(root)

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organise MP3 and FLAC files into artist/album/year/container/quality folders and carry over cover art."
    )
    parser.add_argument(
        "root",
        type=Path,
        help=r'Root folder to scan (e.g. "C:\Music" or "~/Music").',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving/copying files.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them.",
    )
    parser.add_argument(
        "--remove-empty-dirs",
        action="store_true",
        help="Remove empty source folders after moving files.",
    )

    args = parser.parse_args()

    root = args.root.expanduser().resolve()

    if not root.exists():
        print(f"Root folder does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    if not root.is_dir():
        print(f"Root path is not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    organise_music(
        root=root,
        dry_run=args.dry_run,
        copy_only=args.copy,
        remove_empty_dirs=args.remove_empty_dirs,
    )


if __name__ == "__main__":
    main()