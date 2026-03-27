# HUNO API Documentation

Automate your publishing workflow with the HUNO Upload API. Search torrents, manage requests, and upload content programmatically.

## Overview

* **Base URL:** `https://hawke.uno/api`
* **Rate Limiting:** All endpoints are rate-limited to **60 requests per minute** per authenticated user.
* **Format:** Token Auth, JSON responses.

### Standard Response Envelope

All API responses follow a standard envelope format:

```json
{
    "success": true,
    "data": { ... },
    "message": "Description of result."
}
```

---

## Authentication

All API requests require token-based authentication. Your API token is available in **Hub → Settings → Security**.

### Passing the Token

You can pass the token using any of these three methods (Headers are preferred as they keep your token out of server access logs and browser history):

1.  **Authorization Bearer Header (Recommended)**
    ```bash
    curl -H "Authorization: Bearer YOUR_TOKEN" [https://hawke.uno/api/torrents](https://hawke.uno/api/torrents)
    ```
2.  **X-Api-Token Header**
    ```bash
    curl -H "X-Api-Token: YOUR_TOKEN" [https://hawke.uno/api/torrents](https://hawke.uno/api/torrents)
    ```
3.  **Query Parameter**
    ```bash
    GET [https://hawke.uno/api/torrents?api_token=YOUR_TOKEN](https://hawke.uno/api/torrents?api_token=YOUR_TOKEN)
    ```

> **Security Warning:** Never share your API token. It provides full access to your account. If compromised, regenerate it immediately in Security settings.

### Required Permissions

* Your account must have `can_api` enabled.
* Upload endpoints additionally require `can_upload`.

### Error Responses (HTTP Status Codes)

| Code | Status | Description |
| :--- | :--- | :--- |
| `401` | Unauthorized | Invalid or missing API token |
| `403` | Forbidden | Account banned or missing permissions |
| `409` | Conflict | Duplicate content detected |
| `422` | Validation Error | Missing or mismatched fields |
| `429` | Too Many Requests | Rate limit exceeded |

---

## Endpoints Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/torrents/upload` | Upload a torrent (auto or manual mode) |
| `GET` | `/api/torrents` | List recent torrents |
| `GET` | `/api/torrents/filter` | Search & filter torrents |
| `GET` | `/api/torrents/{id}` | Get torrent details |
| `GET` | `/api/requests/filter` | Search & filter requests |
| `GET` | `/api/requests/{id}` | Get request details |
| `GET` | `/api/quicksearch` | Quick search by title/TMDB/IMDB |
| `GET` | `/api/profile` | Your profile stats |

---

## Torrent Endpoints

### Upload Torrent

`POST /api/torrents/upload`

Upload a torrent in auto (recommended) or manual mode. All requests use `multipart/form-data`.

#### Auto Mode (Recommended)
The API parses your torrent filename and MediaInfo to automatically detect all attributes. The name is generated using the HUNO Naming Standard. Release year is sourced from TMDB.

**Example Request:**
```bash
curl -X POST \\
  -H "Content-Type: multipart/form-data" \\
  -H "Accept: application/json" \\
  -F torrent=@"/path/to/file.torrent" \\
  -F category_id=1 \\
  -F type_id=3 \\
  -F tmdb=123456 \\
  -F description=@"/path/to/desc.txt" \\
  -F mediainfo=@"/path/to/mediainfo.txt" \\
  "[https://hawke.uno/api/torrents/upload?api_token=YOUR_TOKEN](https://hawke.uno/api/torrents/upload?api_token=YOUR_TOKEN)"
```

**Auto-Detected Fields (Do not need to be provided in Auto Mode):**
Resolution, Video Codec, Video Format (HDR), Audio Format, Audio Channels, Source Type, Streaming Service, Release Group, Media Language, Release Year, Stream Friendly. 
*(Note: You can override any auto-detected value by providing it explicitly, e.g., `-F video_format=HDR`)*

#### Required Fields

| Field | Type | When | Notes |
| :--- | :--- | :--- | :--- |
| `torrent` | file | Always | `.torrent` file with private flag and source=HUNO |
| `description` | file | Always | `.txt` file with full description (use `@` prefix) |
| `category_id` | int | Always | 1 = Movie, 2 = TV |
| `type_id` | int | Always | 1 = DISC, 2 = REMUX, 3 = WEB, 15 = ENCODE |
| `tmdb` | int | Always | Numeric TMDB ID |
| `mediainfo` | file | Non-DISC | `.txt` file with raw MediaInfo output (use `@` prefix) |
| `bdinfo` | file | DISC only | `.txt` file with BDInfo output |
| `season_number` | int | TV | Season number (0 for specials). Auto mode parses from filename — only needed if parsing fails. |
| `episode_number`| int | TV episodes | Episode number (0 for pilots, omit for season packs). Auto mode parses from filename. |

#### Optional Fields

All attribute fields accept a numeric ID, the abbreviation, or the full name (case-insensitive).

| Field | Notes |
| :--- | :--- |
| `imdb` | IMDB numeric ID (no `tt` prefix) |
| `tvdb` | TVDB numeric ID |
| `mal` | MyAnimeList ID |
| `episode_number_end` | End episode for multi-episode ranges (e.g. 28 for E27-28) |
| `season_pack` | Set to 1 for full season packs |
| `source_mediainfo` | Source material MediaInfo for ENCODE uploads (file, recommended) |
| `anonymous` | 0 or 1 — upload anonymously |
| `internal` | 0 or 1 — mark as internal release (requires internal group) |
| `release_group` | Override auto-detected release group |
| `releaser` | Releaser/encoder name |
| `distributor` | Physical media distributor (Criterion, Arrow, etc.) |
| `edition` | Edition (IMAX, Extended, Director's Cut, etc.) |
| `region` | Region code (USA, GBR, PAL, NTSC, etc.) |
| `scaling_type` | DS4K (downscaled) or AIUS (AI upscaled) |
| `release_tag` | PROPER, REPACK, REPACK2, etc. |

#### Manual Mode

Add `-F mode=manual` for full control. All attributes must be provided explicitly, plus a `name` field.

**Three-Way Validation:** Manual mode validates consistency between all sources:
1. **Name vs Attributes:** your name must match the attributes you provided.
2. **Attributes vs MediaInfo:** your attributes must match the actual file.
3. **Codec Family Matching:** x265, H265, and HEVC are all valid for the `hevc` family.

**Codec Auto-Correction:** If you provide a codec from the correct family but wrong variant for the upload type (e.g., HEVC for a WEB upload), it auto-corrects to the right variant (H265). The name is rebuilt accordingly.

#### Upload Responses

**Success (200)**
```json
{
    "success": true,
    "data": {
        "torrent": { /* torrent details */ },
        "moderation_status": "approved",
        "warnings": [],
        "name_issues": []
    },
    "message": "Torrent uploaded successfully."
}
```

**Attribute Mismatch (422)**
```json
{
    "success": false,
    "data": ["audio_format: you provided 'DTS-HD MA' but MediaInfo shows 'DDP'"],
    "message": "Attribute mismatch."
}
```

**Duplicate Content (409)**
```json
{
    "success": false,
    "data": ["A WEB release with the same attributes already exists from group \\"HONE\\" (ID: 12345)."],
    "message": "Duplicate content."
}
```

### List Recent Torrents
`GET /api/torrents`
Returns the 25 most recent torrents sorted by sticky and bump date. No parameters required.

### Search & Filter Torrents
`GET /api/torrents/filter`
Search and filter torrents with full attribute support. Uses Meilisearch for fast full-text search.

**Parameters:**

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `name` | string | Search by name (all words must match) |
| `categories[]` | int[] | Filter by category IDs |
| `types[]` | int[] | Filter by type IDs |
| `resolutions[]` | int[] | Filter by resolution IDs |
| `tmdbId` | int | Exact TMDB ID match |
| `imdbId` | int | Exact IMDB ID match |
| `tvdbId` | int | Exact TVDB ID match |
| `video_codec_id` | int/int[] | Video codec ID(s) |
| `video_format_id` | int/int[] | Video format ID(s) |
| `audio_format_id` | int/int[] | Audio format ID(s) |
| `audio_channel_id` | int/int[] | Audio channel ID(s) |
| `source_type_id` | int/int[] | Source type ID(s) |
| `streaming_service_id` | int/int[] | Streaming service ID(s) |
| `media_language_id` | int/int[] | Media language ID(s) |
| `uploader` | string | Filter by uploader username |
| `internal` | any | Internal releases only |
| `stream_friendly` | any | Stream-friendly only |
| `alive` | any | Has seeders |
| `dead` | any | No seeders |
| `sortField` | string | `name`, `size`, `seeders`, `leechers`, `times_completed`, `created_at`, `bumped_at` |
| `sortDirection` | string | `asc` or `desc` (default: `desc`) |
| `perPage` | int | Results per page, max 100 (default: 25) |

**Example Request:**
```bash
GET /api/torrents/filter?name=dark+knight&categories[]=1&resolutions[]=2&api_token=KEY
```

### Get Torrent Details
`GET /api/torrents/{id}`
Get full details for a single torrent including description, mediainfo, and download link.

**Response Attributes include:** `name`, `release_year`, `category`, `type`, `resolution`, `video_codec`, `video_format`, `audio_format`, `audio_channels`, `source_type`, `streaming_service`, `media_language`, `distributor`, `edition`, `region`, `release_tag`, `size`, `seeders`, `leechers`, `times_completed`, `tmdb_id`, `imdb_id`, `tvdb_id`, `description`, `mediainfo`, `download_link`.

---

## Requests Endpoints

### Search & Filter Requests
`GET /api/requests/filter`
Search and filter torrent requests.

**Parameters:**

| Parameter | Description |
| :--- | :--- |
| `name` | Search by name |
| `categories[]` | Category ID(s) |
| `types[]` | Type ID(s) |
| `tmdbId` | TMDB ID |
| `imdbId` | IMDB ID |
| `resolution_id` | Resolution ID |
| `video_codec_id`| Video codec ID |
| `audio_format_id`| Audio format ID |
| `source_type_id`| Source type ID |
| `filled` | `true` = filled only |
| `unfilled` | `true` = unfilled only |
| `claimed` | `true` = claimed only |
| `sortField` | `bounty`, `name`, or `created_at` |
| `perPage` | Max 100, default 25 |

### Get Request Details
`GET /api/requests/{id}`
Get full details for a single request including bounty, votes, fill status, and all naming key attributes.

**Response Attributes include:** `name`, `category`, `type`, `resolution`, `video_codec`, `video_format`, `audio_format`, `audio_channels`, `source_type`, `streaming_service`, `bounty`, `votes`, `requester`, `filled_by`, `filled_at`, `claimed`, `description`.

---

## Utility & Account Endpoints

### Quick Search
`GET /api/quicksearch`
Fast title search returning deduplicated results by TMDB ID. Returns up to 10 results.

**Parameters:**
* `query`: Search term, numeric TMDB ID, or IMDB ID (with `tt` prefix)

**Smart Detection:**
* Pure number → filters by TMDB ID
* Starts with `tt` → filters by IMDB ID
* Otherwise → full-text search on torrent name

**Response Example:**
```json
{
    "results": [
        {
            "id": 123,
            "name": "The Dark Knight",
            "year": 2008,
            "category": "Movies",
            "poster": "[https://image.tmdb.org/](https://image.tmdb.org/)...",
            "url": "[https://hawke.uno/torrents/similar/1/155](https://hawke.uno/torrents/similar/1/155)"
        }
    ]
}
```

### Profile
`GET /api/profile`
Returns stats for the authenticated user. No parameters required.

**Notes:** `uploaded` and `downloaded` are in bytes. `ratio` is "Inf" (string) when downloaded is 0.

**Response Example:**
```json
{
    "success": true,
    "data": {
        "username": "hawke",
        "group": "Targaryen",
        "member_since": "2022-01-01T00:00:00+00:00",
        "uploaded": 1099511627776,
        "downloaded": 549755813888,
        "ratio": 2.0,
        "buffer": 549755813888,
        "hunos": 1500,
        "active_seeds": 42,
        "active_leeches": 3,
        "hit_and_runs": 0,
        "seed_divisions": {
            "vanguard": 10,
            "squire": 25,
            "knight": 50,
            "champion": 100,
            "legend": 5,
            "guardian": 3
        },
        "warnings": 0,
        "can_upload": true,
        "can_download": true,
        "can_request": true,
        "can_invite": true
    }
}
```

---

## Attribute Reference

All valid values for attribute fields. Use the ID, Name, or Abbreviation in API requests.

### Core Media Attributes

| ID | Categories | | ID | Types | | ID | Source Types |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Movie | | 1 | DISC | | 1 | UHD BluRay |
| 2 | TV | | 2 | REMUX | | 2 | UHD BluRay Hybrid |
| | | | 3 | WEB | | 3 | BluRay |
| | | | 15 | ENCODE | | 4 | BluRay Hybrid |
| | | | | | | 5 | HD-DVD |
| | | | | | | 6 | HD-DVD Hybrid |
| | | | | | | 7 | DVD9 |
| | | | | | | 8 | DVD5 |
| | | | | | | 9 | WEB-DL |
| | | | | | | 10 | WEB-DL Hybrid |
| | | | | | | 11 | HDTV |
| | | | | | | 12 | SDTV |
| | | | | | | 13 | DVD |

### Video & Resolution Attributes

| ID | Resolutions | | ID | Video Codecs | | ID | Video Formats | | ID | Scaling Types |
| :---| :--- | :---| :---| :--- | :---| :---| :--- | :---| :---| :--- |
| 1 | 4320p | | 1 | x265 | | 1 | DV HDR10+ | | 1 | DS4K |
| 2 | 2160p | | 2 | x264 | | 2 | DV HDR | | 2 | AIUS |
| 3 | 1080p | | 3 | H265 | | 3 | DV | | | |
| 4 | 1080i | | 4 | H264 | | 4 | HDR10+ | | | |
| 5 | 720p | | 5 | HEVC | | 5 | HDR | | | |
| 6 | 576p | | 6 | AVC | | 6 | PQ10 | | | |
| 7 | 576i | | 7 | VC-1 | | 7 | HLG | | | |
| 11| 540p | | 8 | MPEG-2 | | 8 | SDR | | | |
| 8 | 480p | | 9 | AV1 | | | | | | |
| 9 | 480i | | | | | | | | | |
| 10| Other | | | | | | | | | |

### Audio Attributes

| ID | Audio Formats | | ID | Audio Channels |
| :--- | :--- | :--- | :--- | :--- |
| 1 | TrueHD Atmos | | 1 | 13.1 Surround (Auro3D) |
| 2 | TrueHD | | 2 | 12.1 Surround (Auro3D) |
| 3 | DTS-HD MA Auro3D | | 3 | 11.1 Surround (Auro3D) |
| 4 | DTS-HD MA | | 4 | 10.1 Surround (Auro3D) |
| 5 | DTS-HD HRA | | 5 | 9.1 Surround (Auro3D) |
| 6 | DTS:X | | 6 | 7.1 Surround |
| 7 | DTS | | 7 | 6.1 Surround |
| 8 | DDP Atmos | | 8 | 5.1 Surround |
| 9 | DDP | | 9 | 5.0 Surround |
| 10 | DD | | 10 | 4.0 Surround |
| 11 | AAC | | 11 | 2.1 Stereo |
| 12 | FLAC | | 12 | 2.0 Stereo |
| 13 | LPCM | | 13 | 1.0 Mono |
| 14 | MP3 | | 14 | No Audio |
| 15 | MP2 | | | |
| 16 | VORBIS | | | |
| 17 | OPUS | | | |
| 18 | NONE | | | |

### Streaming Services
*(IDs 1-194 mapped to standard abbreviations. Here are the most common; others can be referenced by the internal IDs if listed in full. Claude will be able to search for specific IDs across this subset)*

| ID | Service | ID | Service | ID | Service | ID | Service | ID | Service | ID | Service |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| 1 | NF | 2 | AMZN | 3 | DSNP | 4 | ATVP | 5 | MAX | 6 | HMAX |
| 7 | HBO | 8 | HULU | 9 | PCOK | 10 | PMTP | 11 | ATV | 12 | iT |
| 13 | PLAY | 14 | YT | 15 | RED | 16 | MS | 17 | XBOX | 18 | PSN |
| 19 | SHO | 20 | STZ | 21 | MGMP | 22 | EPIX | 23 | CMAX | 24 | DSCP |
| 25 | DISC | 26 | VLCT | 27 | TLC | 28 | HGTV | 29 | FOOD | 30 | COOK |
| 31 | DIY | 32 | ANPL | 33 | DEST | 34 | ID | 35 | TRVL | 36 | MTOD |
| 37 | AMBC | 38 | CBS | 39 | NBC | 40 | FOX | 41 | CW | 42 | CWS |
| 43 | PBS | 44 | PBSK | 45 | AMC | 46 | AE | 47 | HIST | 48 | LIFE |
| 49 | FYI | 50 | PMNT | 51 | SPIK | 52 | TVL | 53 | USAN | 54 | SYFY |
| 55 | ETV | 56 | OXGN | 57 | BRAV | 58 | TBS | 59 | FREE | 60 | IFC |
| 61 | HLMK | 62 | NATG | 63 | MTV | 64 | VH1 | 65 | CC | 66 | NICK |
| 67 | CMT | 68 | DSNY | 69 | APPS | 70 | CNN | 71 | MNBC | 72 | CNBC |
| 73 | CSPN | 74 | AJAZ | 75 | ESPN | 76 | NBA | 77 | NFL | 78 | NFLN |
| 79 | GC | 80 | UFC | 81 | iP | 82 | ITV | 83 | NOW | 84 | UKTV |
| 85 | SKST | 86 | CRAV | 87 | CBC | 88 | CLBI | 89 | TOU | 90 | GLBL |
| 91 | SHMI | 92 | WNET | 93 | FAM | 94 | FJR | 95 | KNOW | 96 | SNET |
| 97 | STAN | 98 | BNGE | 99 | FXTL | 100| SBS | 101| AUBC | 102| 9NOW |
| 103| TEN | 104| KAYO | 105| CNLP | 106| FTV | 107| TFOU | 108| ARD |
| 109| ZDF | 110| VIAP | 111| CMOR | 112| NRK | 113| SVT | 114| TV4 |
| 115| DRTV | 116| RTE | 117| TV3 | 118| RPLAY | 119| STRP | 120| GLOB |
| 121| UNIV | 122| ETTV | 123| HSTR | 124| JC | 125| HPLAY | 126| MMAX |
| 127| SNXT | 128| LGP | 129| SAINA | 130| SS | 131| TK | 132| VIKI |
| 133| ODK | 134| TVING | 135| MBC | 136| FPT | 137| TVNZ | 138| PUHU |
| 139| DDY | 140| CRIT | 141| MUBI | 142| SHDR | 143| DCU | 144| KNPY |
| 145| BCORE | 146| KS | 147| MA | 148| TUBI | 149| ROKU | 150| CRKL |
| 151| PLEX | 152| PLUZ | 153| AS | 154| BOOM | 155| SESO | 156| GO90 |
| 157| AOL | 158| YHOO | 159| QIBI | 160| FBWATCH| 161| SLNG | 162| SPRT |
| 163| ESQ | 164| CUR | 165| BKPL | 166| DHF | 167| DOCC | 168| DPLY |
| 169| DRPO | 170| LN | 171| POGO | 172| PA | 173| RKTN | 174| RSTR |
| 175| SWER | 176| TIMV | 177| VTRN | 178| VICE | 179| VMEO | 180| WME |
| 181| CHRGD | 182| WWEN | 183| ATK | 184| CCGC | 185| YKW | 186| NADA |
| 187| CR | 189| ALL4 | 190| MGTV | 191| MY5 | 192| ANGL | 193| BRTB |
| 194| BYUT | | | | | | | | |

### General Metadata Tags

| ID | Distributors | ID | Editions | ID | Regions | ID | Release Tags |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Criterion | 1 | IMAX | 1 | PAL | 1 | REPACK |
| 2 | BFI | 2 | OPEN MATTE | 2 | NTSC | 2 | REPACK2 |
| 3 | Arrow | 3 | Extended | 3 | RA | 3 | REPACK3 |
| 4 | Shout | 4 | Ultimate | 4 | RB | 4 | PROPER |
| 5 | Indicator | 5 | Directors Cut| 5 | RC | 5 | PROPER2 |
| 6 | Eureka | 6 | Theatrical | 6 | RF | 6 | INCOMPLETE |
| 7 | Kino | 7 | Anniversary | 7 | USA | 7 | DUBBED |
| 8 | Second Sight | 8 | Special | 8 | GBR | 8 | SUBBED |
| 9 | TT | 9 | Limited | 9 | DEU | | |
| 10 | VS | 10 | Collectors | 10 | FRA | | |
| 11 | 88 | 11 | Unrated | 11 | ITA | | |
| 12 | Imprint | 12 | Uncut | 12 | ESP | | |
| 13 | Umbrella | 13 | Criterion | 13 | JPN | | |
| 14 | Severin | 14 | Final Cut | 14 | KOR | | |
| 15 | BU | 15 | Redux | 15 | CHN | | |
| 16 | Synapse | 16 | Restored | 16 | HKG | | |
| 17 | Scream | 17 | 3D | 17 | TWN | | |
| 18 | Mill Creek | 18 | Assembly | 18 | AUS | | |
| 19 | WA | 19 | Remastered | 19 | CAN | | |
| 20 | SPC | 20 | 4K Remaster | 20 | NLD | | |
| 21 | Universal | 21 | Superbit | 21 | SWE | | |
| 22 | Paramount | | | 22 | NOR | | |
| 23 | Disney | | | 23 | DNK | | |
| 24 | Lionsgate | | | 24 | POL | | |
| 25 | A24 | | | 25 | RUS | | |
| | | | | 26 | BRA | | |
| | | | | 27 | MEX | | |
| | | | | 28 | IND | | |

### Media Languages (Selection)
*(Most common selections by ID. Claude can match partials natively through standard queries)*
* **English:** 38
* **Spanish:** 40
* **French:** 48
* **German:** 33
* **Italian:** 73
* **Japanese:** 75
* **Korean:** 85
* **Mandarin:** 186
* **Hindi:** 58
* **Russian:** 137
* **DUAL:** 188
* **MULTI:** 189
* **No Language:** 182
*(The API supports 180+ languages mapped to numeric IDs; provide string queries in manual upload/search if uncertain).