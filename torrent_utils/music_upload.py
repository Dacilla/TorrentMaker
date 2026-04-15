"""Music upload scanning and tracker payload helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

import mutagen


AUDIO_EXTENSIONS = {".mp3", ".flac"}
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png")
LOG_EXTENSIONS = {".log", ".cue"}
WEB_MEDIA = {"WEB"}
BLOCKED_MEDIA_WITHOUT_LOG_SUPPORT = {"CD"}

RELEASE_TYPE_IDS = {
    "Album": 1,
    "Soundtrack": 3,
    "EP": 5,
    "Anthology": 6,
    "Compilation": 7,
    "Single": 9,
    "Live album": 11,
    "Remix": 13,
    "Bootleg": 14,
    "Interview": 15,
    "Mixtape": 16,
    "Demo": 17,
    "Concert Recording": 18,
    "DJ Mix": 19,
    "Unknown": 21,
}


@dataclass
class TrackInfo:
    path: str
    disc: str
    track_number: int | None
    total_tracks: int | None
    title: str | None
    format: str | None
    bitrate: str | None
    md5_missing: bool = False


@dataclass
class MusicUploadMetadata:
    artist: str
    title: str
    year: int | None
    release_type: str
    audio_format: str | None
    bitrate: str | None
    media: str
    tags: str
    image: str
    record_label: str | None = None
    edition_year: int | None = None
    release_group_id: str | None = None

    @property
    def identity_key(self) -> tuple[str, str, int | None, str]:
        return (
            normalize_identity_value(self.artist),
            normalize_identity_value(self.title),
            self.year,
            normalize_identity_value(self.release_type),
        )


@dataclass
class AlbumScan:
    path: str
    metadata: MusicUploadMetadata
    tracks: list[TrackInfo] = field(default_factory=list)
    cover_path: str | None = None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    group_match_status: str = "not checked"

    @property
    def ok(self) -> bool:
        return not self.blockers


def normalize_identity_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def format_tracker_tags(tags: str) -> str:
    processed = (tags or "").replace("/", ",").replace("&", ",")
    return ", ".join(
        part.strip().replace(" ", ".").lower()
        for part in processed.split(",")
        if part.strip()
    )


def split_artists(artists: str | Iterable[str]) -> list[str]:
    if isinstance(artists, str):
        candidates = artists.split(",")
    else:
        candidates = list(artists)
    return [artist.strip() for artist in candidates if artist and artist.strip()]


def infer_release_type(track_count: int) -> str:
    if track_count < 3:
        return "Single"
    if track_count <= 5:
        return "EP"
    return "Album"


def extract_label_from_text(copyright_text: str | None, artist: str | None = None) -> str | None:
    if not copyright_text:
        return None
    label = re.sub(r"\b\d{4}\b", "", copyright_text)
    label = re.sub(r"[™©®℗]", "", label)
    label = label.split(", ")[0].strip()
    words = []
    for word in label.split():
        if word not in words:
            words.append(word)
    label = " ".join(words)
    label = label.lower().split("under exclusive")[0].strip()
    if not label:
        return None
    if artist and normalize_identity_value(label) == normalize_identity_value(artist):
        return "Self-Released"
    if "records dk" in label.lower():
        return "Self-Released"
    return label


def _audio_files(folder_path: str) -> list[str]:
    files = []
    for root, _, names in os.walk(folder_path):
        for name in sorted(names):
            ext = os.path.splitext(name)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                files.append(os.path.join(root, name))
    return sorted(files)


def _first(values: Any) -> Any:
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return values


def _tag(audio: Any, key: str) -> Any:
    if not audio:
        return None
    try:
        return _first(audio.get(key))
    except AttributeError:
        return None


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def _parse_track_number(value: Any) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    first = str(value).split(";")[0].strip()
    parts = first.split("/")
    number = int(parts[0]) if parts and parts[0].isdigit() else None
    total = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return number, total


def _disc_name(folder_path: str, file_path: str) -> str:
    rel = os.path.relpath(os.path.dirname(file_path), folder_path)
    if rel == ".":
        return "1"
    basename = os.path.basename(rel)
    match = re.search(r"(\d+)$", basename)
    return match.group(1) if match else rel


def _format_from_file(file_path: str, audio: Any) -> str | None:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".flac":
        return "FLAC"
    if ext == ".mp3":
        return "MP3"
    mime = getattr(audio, "mime", [""])[0] if audio else ""
    if mime == "audio/flac":
        return "FLAC"
    if mime == "audio/mp3":
        return "MP3"
    return None


def _bitrate_from_audio(audio_format: str | None, audio: Any) -> str | None:
    info = getattr(audio, "info", None)
    if audio_format == "FLAC":
        bits = getattr(info, "bits_per_sample", None)
        if bits == 16:
            return "Lossless"
        if bits == 24:
            return "24bit Lossless"
        return None
    if audio_format == "MP3":
        bitrate = getattr(info, "bitrate", None)
        if bitrate:
            kbps = int(round(bitrate / 1000))
            for accepted in (320, 256, 192):
                if abs(kbps - accepted) <= 2:
                    return str(accepted)
        return None
    return None


def _find_cover(folder_path: str, cover_path: str | None = None) -> str | None:
    if cover_path:
        return cover_path if os.path.exists(cover_path) else None
    for name in COVER_NAMES:
        candidate = os.path.join(folder_path, name)
        if os.path.exists(candidate):
            return candidate
    for root, _, files in os.walk(folder_path):
        for name in files:
            if name.lower() in COVER_NAMES:
                return os.path.join(root, name)
    return None


def _has_log_or_cue(folder_path: str) -> bool:
    for _, _, files in os.walk(folder_path):
        for name in files:
            if os.path.splitext(name)[1].lower() in LOG_EXTENSIONS:
                return True
    return False


def _path_length_ok(folder_path: str) -> bool:
    for root, _, files in os.walk(folder_path):
        for file_name in files:
            if len(os.path.basename(root)) + len(file_name) > 180:
                return False
    return True


def scan_album(
    folder_path: str,
    media: str = "WEB",
    tags_override: str | None = None,
    cover_path: str | None = None,
    original_year: int | None = None,
    release_type_override: str | None = None,
) -> AlbumScan:
    """Inspect a music folder and return upload metadata plus fail-closed blockers."""
    blockers: list[str] = []
    warnings: list[str] = []
    audio_paths = _audio_files(folder_path)

    if not os.path.isdir(folder_path):
        blockers.append("path is not a directory")
    if not audio_paths:
        blockers.append("no supported audio files found")

    tracks: list[TrackInfo] = []
    first_audio = mutagen.File(audio_paths[0], easy=True) if audio_paths else None
    artist = _tag(first_audio, "albumartist") or _tag(first_audio, "artist") or ""
    title = _tag(first_audio, "album") or ""
    first_year = _parse_year(_tag(first_audio, "date") or _tag(first_audio, "year"))
    year = original_year or first_year
    raw_tags = tags_override if tags_override is not None else (_tag(first_audio, "genre") or "")
    copyright_text = _tag(first_audio, "copyright")
    record_label = extract_label_from_text(copyright_text, artist)

    formats = set()
    bitrates = set()
    tracks_by_disc: dict[str, list[int]] = {}
    total_tracks = 0
    missing_md5 = False

    for audio_path in audio_paths:
        audio = mutagen.File(audio_path, easy=True)
        technical_audio = mutagen.File(audio_path)
        audio_format = _format_from_file(audio_path, technical_audio)
        bitrate = _bitrate_from_audio(audio_format, technical_audio)
        number, total = _parse_track_number(_tag(audio, "tracknumber"))
        disc = _disc_name(folder_path, audio_path)
        title_tag = _tag(audio, "title")

        if audio_format:
            formats.add(audio_format)
        if bitrate:
            bitrates.add(bitrate)
        if number is not None:
            tracks_by_disc.setdefault(disc, []).append(number)
        else:
            blockers.append(f"missing track number: {os.path.basename(audio_path)}")

        md5_empty = False
        if audio_format == "FLAC":
            info = getattr(technical_audio, "info", None)
            md5_empty = not bool(getattr(info, "md5_signature", None))
            missing_md5 = missing_md5 or md5_empty

        tracks.append(
            TrackInfo(
                path=audio_path,
                disc=disc,
                track_number=number,
                total_tracks=total,
                title=title_tag,
                format=audio_format,
                bitrate=bitrate,
                md5_missing=md5_empty,
            )
        )
        total_tracks += 1

    for disc, numbers in tracks_by_disc.items():
        for expected in range(1, max(numbers) + 1):
            if expected not in numbers:
                blockers.append(f"missing track {expected} on disc {disc}")

    if not artist:
        blockers.append("missing album artist")
    if not title:
        blockers.append("missing album title")
    if not year:
        blockers.append("missing release year")
    if not raw_tags:
        blockers.append("missing genre/tags")
    if not _path_length_ok(folder_path):
        blockers.append("one or more file paths are too long")
    if len(formats) > 1:
        blockers.append("mixed audio formats in one folder")
    if len(bitrates) > 1:
        blockers.append("mixed bitrate/bit-depth in one folder")
    if audio_paths and not bitrates:
        blockers.append("unsupported or undetected bitrate/bit-depth")
    if missing_md5:
        blockers.append("one or more FLAC files have missing MD5 signatures")

    found_cover = _find_cover(folder_path, cover_path)
    if not found_cover:
        blockers.append("missing cover image")

    normalized_media = (media or "WEB").strip()
    if normalized_media.upper() in BLOCKED_MEDIA_WITHOUT_LOG_SUPPORT:
        blockers.append("CD uploads require log/CUE attachment support before upload")
    elif normalized_media.upper() not in WEB_MEDIA and not _has_log_or_cue(folder_path):
        warnings.append(f"{normalized_media} upload has no log/CUE files")

    audio_format = next(iter(formats)) if len(formats) == 1 else None
    bitrate = next(iter(bitrates)) if len(bitrates) == 1 else None
    release_type = release_type_override or infer_release_type(total_tracks)

    metadata = MusicUploadMetadata(
        artist=artist,
        title=title,
        year=year,
        release_type=release_type,
        audio_format=audio_format,
        bitrate=bitrate,
        media=normalized_media,
        tags=format_tracker_tags(raw_tags),
        image="",
        record_label=record_label,
        edition_year=first_year if original_year and first_year and first_year != original_year else None,
    )
    return AlbumScan(
        path=folder_path,
        metadata=metadata,
        tracks=tracks,
        cover_path=found_cover,
        blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
    )


def with_metadata_overrides(
    metadata: MusicUploadMetadata,
    *,
    image: str | None = None,
    release_type: str | None = None,
    release_group_id: str | None = None,
    edition_year: int | None = None,
) -> MusicUploadMetadata:
    return replace(
        metadata,
        image=image if image is not None else metadata.image,
        release_type=release_type or metadata.release_type,
        release_group_id=release_group_id if release_group_id is not None else metadata.release_group_id,
        edition_year=edition_year if edition_year is not None else metadata.edition_year,
    )


def validate_metadata_for_payload(metadata: MusicUploadMetadata) -> list[str]:
    blockers = []
    if not metadata.artist:
        blockers.append("missing album artist")
    if not metadata.title:
        blockers.append("missing album title")
    if not metadata.year:
        blockers.append("missing release year")
    if not metadata.audio_format:
        blockers.append("missing audio format")
    if not metadata.bitrate:
        blockers.append("missing bitrate")
    if not metadata.tags:
        blockers.append("missing genre/tags")
    if not metadata.image:
        blockers.append("missing uploaded image URL")
    if metadata.release_type not in RELEASE_TYPE_IDS:
        blockers.append(f"unsupported release type: {metadata.release_type}")
    return blockers


def _artist_fields(artists: str | Iterable[str]) -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []
    for artist in split_artists(artists):
        fields.append(("artists[]", artist))
        fields.append(("importance[]", 1))
    return fields


def _decade_tag(year: int | None) -> str | None:
    if not year:
        return None
    return f"{str(year)[:3]}0s"


def build_red_payload(
    metadata: MusicUploadMetadata,
    album_desc: str,
    *,
    group_id: int | None = None,
    dryrun: bool = False,
    no_desc: bool = False,
) -> list[tuple[str, Any]]:
    blockers = validate_metadata_for_payload(metadata)
    if blockers:
        raise ValueError("; ".join(blockers))

    tags = metadata.tags
    decade = _decade_tag(metadata.year)
    if decade and decade not in [tag.strip() for tag in tags.split(",")]:
        tags = f"{tags}, {decade}" if tags else decade

    payload: list[tuple[str, Any]] = [
        ("type", 0),
        ("title", metadata.title),
        ("year", metadata.year),
        ("releasetype", RELEASE_TYPE_IDS[metadata.release_type]),
        ("format", metadata.audio_format),
        ("bitrate", metadata.bitrate),
        ("media", metadata.media),
        ("image", metadata.image),
        ("tags", tags),
    ]
    if dryrun:
        payload.append(("dryrun", 1))
    if not no_desc:
        payload.append(("album_desc", album_desc))
    if group_id:
        payload.append(("groupid", group_id))
    if metadata.record_label:
        payload.append(("remaster_year", metadata.edition_year or metadata.year))
        payload.append(("remaster_record_label", metadata.record_label))
    elif metadata.edition_year:
        payload.append(("remaster_year", metadata.edition_year))
    payload.extend(_artist_fields(metadata.artist))
    return payload


def build_ops_payload(
    metadata: MusicUploadMetadata,
    album_desc: str,
    *,
    group_id: int | None = None,
) -> list[tuple[str, Any]]:
    blockers = validate_metadata_for_payload(metadata)
    if blockers:
        raise ValueError("; ".join(blockers))

    payload: list[tuple[str, Any]] = [
        ("type", 0),
        ("title", metadata.title),
        ("year", metadata.year),
        ("releasetype", RELEASE_TYPE_IDS[metadata.release_type]),
        ("format", metadata.audio_format),
        ("bitrate", metadata.bitrate),
        ("media", metadata.media),
        ("tags", metadata.tags),
        ("image", metadata.image),
        ("album_desc", album_desc),
        ("release_desc", ""),
    ]
    if group_id:
        payload.append(("groupid", group_id))
    if metadata.record_label:
        payload.append(("record_label", metadata.record_label))
        payload.extend((
            ("remaster", 1),
            ("remaster_year", metadata.edition_year or metadata.year),
            ("remaster_record_label", metadata.record_label),
        ))
    elif metadata.edition_year:
        payload.extend((("remaster", 1), ("remaster_year", metadata.edition_year)))
    payload.extend(_artist_fields(metadata.artist))
    return payload


def render_preflight_table(scans: list[AlbumScan]) -> str:
    headers = ["Folder", "Artist", "Album", "Year", "Type", "Format", "Bitrate", "Media", "Tags", "Cover", "Group", "Status"]
    rows = []
    for scan in scans:
        meta = scan.metadata
        rows.append(
            [
                os.path.basename(scan.path),
                meta.artist or "-",
                meta.title or "-",
                str(meta.year or "-"),
                meta.release_type or "-",
                meta.audio_format or "-",
                meta.bitrate or "-",
                meta.media or "-",
                meta.tags or "-",
                "yes" if scan.cover_path else "no",
                scan.group_match_status,
                "OK" if scan.ok else "; ".join(scan.blockers),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(str(value))) for width, value in zip(widths, row)]

    def fmt(row: list[Any]) -> str:
        return " | ".join(str(value).ljust(width) for value, width in zip(row, widths))

    divider = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), divider] + [fmt(row) for row in rows])
