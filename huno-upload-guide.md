# HUNO Upload Guide

The upload guide is divided into convenient sections as presented below. You can click on each section header to expand it (in the original UI).

---

## STEP 1 --- PREPARING FILES FOR UPLOAD

### FILE NAME
For personal releases, it is recommended to include the Title, Year, and Resolution at the very least, as good practice. If uploading someone else's release, do not rename or modify the file(s). The upload form will parse the torrent filename automatically to detect attributes.

### FOLDERS
For personal releases, it is recommended to avoid folders for single files. If uploading someone else's release, retain the original folder structure, if any.

### BANNED RELEASE GROUPS
Releases from certain groups are banned on HUNO. The upload form will automatically detect and block banned groups. If your upload is from a banned group, it will be rejected during submission.

Additionally, **bit-starved encodes are banned on HUNO**. 
* If using CRF, **22** is the absolute minimum. 
* If using two-pass ABR, a minimum bitrate of **3000 kb/s** is required for 1080p live action content, with other resolutions and content types being dealt with on a case by case basis. 
* Encodes may still be rejected for any other reason at staff discretion.

---

## STEP 2 --- THE UPLOAD FORM

The upload form is organised into tabs: **Details, Description, MediaInfo, and BDInfo** (for DISC uploads). Each tab shows a checkmark when complete. All tabs must be complete before the Submit button is enabled.

### TORRENT FILE
Upload your `.torrent` file at the top of the form. Once uploaded, the system automatically parses the torrent filename to detect the title, year, resolution, codec, audio format, source type, streaming service, release group, season/episode numbers, and more. These are used to auto-fill the attribute fields in the Details tab.

HUNO modifies the `.torrent` file during upload to include the correct tracker metadata (announce URL, source flag). You can prepare your torrent with HUNO metadata from the start using the Announce URL and Source Flag shown at the top of the upload form, which avoids needing to re-download the `.torrent` file after uploading.

**Example `mktorrent` command:**
```bash
mktorrent -p -v -l 19 -a '[https://hawke.uno/announce/passkey](https://hawke.uno/announce/passkey)' -o "/path/to/output.torrent" "filename.mkv" -s HUNO
```
*(Passkey (PID) can be found under Settings -> Security of your user hub or in the Announce URL on the upload page.)*

### POST NAME (Auto-Generated)
The post name is automatically generated from the attributes you select in the Details tab using the **HUNO Naming Standard**. You do not need to type the name manually. As you fill in or change attribute fields, the name updates in real-time.

The naming structure varies by category and type:

**MOVIE**
* **REMUX:** `TTL (RYR) EDN (RES SRC TYP PRO VFT AFT CHN LNG - CRU) [RLS]`
* **WEB:** `TTL (RYR) EDN (RES SRV SRC PRO VFT AFT CHN LNG - CRU) [RLS]`
* **ENCODE:** `TTL (RYR) EDN (RES SRV SRC PRO VFT AFT CHN LNG - RLR CRU) [RLS]`
* **DISC:** `TTL (RYR) EDN (RES RGN SRC PRO VFT AFT CHN LNG - CRU) [RLS]`

**TV EPISODE**
* **REMUX:** `TTL (RYR) SXXEXX EDN (RES SRC TYP PRO VFT AFT CHN LNG - CRU) [RLS]`
* **WEB:** `TTL (RYR) SXXEXX EDN (RES SRV SRC PRO VFT AFT CHN LNG - CRU) [RLS]`
* **ENCODE:** `TTL (RYR) SXXEXX EDN (RES SRV SRC PRO VFT AFT CHN LNG - RLR CRU) [RLS]`
* **DISC:** `TTL (RYR) SXXEXX EDN (RES RGN SRC PRO VFT AFT CHN LNG - CRU) [RLS]`

**TV SEASON PACK**
* **REMUX:** `TTL (RYR) SXX EDN (RES SRC TYP PRO VFT AFT CHN LNG - CRU) [RLS]`
* **WEB:** `TTL (RYR) SXX EDN (RES SRV SRC PRO VFT AFT CHN LNG - CRU) [RLS]`
* **ENCODE:** `TTL (RYR) SXX EDN (RES SRV SRC PRO VFT AFT CHN LNG - RLR CRU) [RLS]`
* **DISC:** `TTL (RYR) SXX EDN (RES RGN SRC PRO VFT AFT CHN LNG - CRU) [RLS]`

*Key differences by type: REMUX includes TYP (remux indicator). WEB and ENCODE include SRV (streaming service). DISC includes RGN (region). Only ENCODE includes RLR (individual releaser).*

### DETAILS TAB
This tab contains all the attribute fields. Fields marked with `*` are mandatory. Most fields are auto-filled from the torrent filename and MediaInfo, but you can adjust them manually if needed.

**Always mandatory:**
* **Category** — Movies or TV
* **Type** — DISC, REMUX, WEB, or ENCODE
* **TMDB ID** — auto-detected from title, or enter manually
* **Source Type** — e.g. BluRay, WEB-DL, UHD BluRay, HDTV
* **Video Format (HDR)** — e.g. SDR, HDR, DV, DV HDR, HDR10+
* **Audio Format** — e.g. TrueHD Atmos, DTS-HD MA, DDP, FLAC
* **Audio Channels** — e.g. 7.1, 5.1, 2.0
* **Media Language** — primary audio language
* **Release Group (CRU)** — the group/crew tag, e.g. HUNO, FraMeSToR. Use `NOGRP` if unknown

**Conditionally mandatory:**
* **Resolution** — mandatory for Movie/TV (e.g. 2160p, 1080p, 720p)
* **Video Codec** — mandatory for non-DISC (e.g. x265, HEVC, AVC)
* **Streaming Service** — mandatory for WEB type (e.g. NF, AMZN, DSNP)
* **Season Number** — mandatory for TV uploads
* **Episode Number** — mandatory for TV single episodes (not season packs)

**Optional fields:**
* **Distributor** — for DISC/REMUX from notable distributors (Criterion, Arrow, etc.)
* **Edition** — IMAX, Extended, Directors Cut, Theatrical, etc.
* **Region** — for DISC/REMUX (Region A/B/C, PAL, NTSC)
* **Scaling Type** — for ENCODE (DS4K for downscaled from 4K)
* **Release Tag** — REPACK, PROPER, etc.
* **Releaser (RLR)** — individual encoder name (optional)

### DESCRIPTION TAB
Write or paste your upload description. Supports BBCode and Markdown formatting. A minimum of three, full-frame, full-resolution screenshots with consistent tonemapping must be included. For encodes, the source name and size should also be specified.

### MEDIAINFO TAB
Paste the full raw MediaInfo of the file being uploaded. For season packs, paste the MediaInfo from any single episode.

* Mandatory for all types **except DISC**. The system extracts attributes from the MediaInfo (resolution, codec, HDR format, audio format, channels, language) and cross-validates them against your selected attributes. Any mismatches are flagged as warnings.
* For **ENCODE** uploads, the MediaInfo must include **Encoding settings**. This proves the file was actually encoded and not just remuxed. Encodes missing encoding settings are not allowed.
* **Source MediaInfo** — additionally mandatory for ENCODE uploads. Paste the MediaInfo of the source material used for the encode (e.g. the REMUX or WEB-DL you encoded from). This helps verify encode quality and enables smart moderation rules. The system auto-detects the source resolution, codec, and HDR format from it.

### BDINFO TAB
Paste the full raw BDInfo of the disc being uploaded. Mandatory for the **DISC** type only. For season packs, paste the BDInfo from any single disc.

### TYPE REQUIREMENTS

* **REMUX**
  * For remuxes from UHD BluRays, BluRays, and DVDs only.
* **WEB**
  * For WEB-DLs direct from streaming sources.
  * AV1, H265, and H264 true WEB-DLs only.
* **ENCODE**
  * x264, x265, and AV1 encodes of media from REMUX, WEB, or (U)HDTV sources.
  * Must contain encoding settings in the raw MediaInfo.
  * For AV1 encoders that do not put the settings in mediainfo, settings must be provided in the torrent description.
  * Must provide source MediaInfo when known.
  * Must not be hardware encodes (e.g. NVENC).
* **DISC**
  * Full discs from UHD BluRays, BluRays, and DVDs only.
  * BDInfo is required instead of MediaInfo.

### SPECIAL TAGS
* **ANONYMOUS** — hides your username from all viewers except staff.
* **STREAM FRIENDLY** — for media files whose video and audio streams are both compatible with direct streaming.
* **SEASON PACK** — for uploading a full season. A single upload must not include multiple seasons.

---

## STEP 3 --- SUBMISSION & MODERATION

The **Submit** button is enabled once all required tabs show a checkmark and there are no blocking rule violations. Upload rules are evaluated in real-time as you fill in the form — any violations appear as alerts above the submit button.

Double check all fields and ensure compliance. Click **Submit Torrent** at the bottom of the form. 
Your upload will be routed through smart moderation rules. Depending on the result, your torrent will be:
* **Approved** — immediately visible and downloadable
* **Pending** — queued for staff review
* **Postponed** — needs changes before approval

*(Trusted uploaders have their uploads auto-approved.)*

* If the uploaded `.torrent` file was created with HUNO metadata (announce URL + source flag), head to your torrent client and click "Update Tracker". The torrent should show "Announce OK".
* If the `.torrent` file was not created with HUNO metadata, download the `.torrent` file from the torrent page after uploading and add it to your client.

You can also edit your upload after submission by clicking the **Edit** button on the torrent detail page. This opens the same upload interface in edit mode where you can adjust attributes, description, and MediaInfo.

For help, reach out in `#basement` on our Discord.

---

## THE HUNO NAMING KEY

The post name is auto-generated from the attributes you select. These are the naming key tags used in the structure:

* **TTL** — The English title as per TMDB. AKAs are not permitted.
* **RYR** — Four-digit year of release as per TMDB. For TV, the year of the first episode of S01.
* **SXX** — Season number (two digits, as per TVDB). Use `S00` for specials.
* **SXXEXX** — Combined season and episode number (e.g. `S01E05`, as per TVDB).
* **EDN** — Edition name. Values: `IMAX, OPEN MATTE, Extended, Ultimate, Directors Cut, Theatrical, Anniversary, Special, Limited, Collectors, Unrated, Uncut, Criterion, Final Cut, Redux, Restored, 3D, Assembly, Remastered, 4K Remaster, Superbit`
* **RES** — Resolution. Values: `4320p, 2160p, 1080p, 1080i, 720p, 576p, 576i, 540p, 480p, 480i`
* **SCL** — Scaling type (ENCODE requests only). Values: `DS4K, AIUS`
* **SRV** — Streaming service tag (WEB/ENCODE only). Values: `NF, AMZN, DSNP, ATVP, MAX, HMAX, HBO, HULU, PCOK, PMTP, ATV, iT, PLAY, YT, RED, SHO, STZ` and many more.
* **RGN** — Region (DISC only). Values: `PAL, NTSC, RA, RB, RC, RF, USA, GBR, DEU, FRA, ITA, ESP, JPN, KOR, CHN, HKG, TWN, AUS, CAN` and more.
* **SRC** — Source type. Values: `UHD BluRay, UHD BluRay Hybrid, BluRay, BluRay Hybrid, HD-DVD, HD-DVD Hybrid, DVD9, DVD5, WEB-DL, WEB-DL Hybrid, HDTV, SDTV, DVD`
* **TYP** — Upload type (REMUX patterns only). Values: `REMUX, WEB, ENCODE, DISC`
* **PRO** — Video codec / process. Values: `x265, x264, H265, H264, HEVC, AVC, VC-1, MPEG-2, AV1`
* **VFT** — Video format / HDR type. Values: `DV HDR10+, DV HDR, DV, HDR10+, HDR, PQ10, HLG, SDR`
* **AFT** — Audio format. Values: `TrueHD Atmos, TrueHD, DTS-HD MA Auro3D, DTS-HD MA, DTS-HD HRA, DTS:X, DTS, DDP Atmos, DDP, DD, AAC, FLAC, LPCM, MP3, MP2, VORBIS, OPUS, NONE`
* **CHN** — Audio channels (base layer only, ignoring Atmos height). Values: `13.1, 12.1, 11.1, 10.1, 9.1, 7.1, 6.1, 5.1, 5.0, 4.0, 2.1, 2.0, 1.0, 0.0`
* **LNG** — Language of the primary audio track. Common values: `English, French, German, Spanish, Japanese, Korean, Mandarin, Cantonese, Italian, Portuguese, Hindi, Russian, Arabic, Swedish, Dutch, Polish, Turkish, Thai, Vietnamese` and 160+ more. Use `DUAL` for two languages, `MULTI` for three or more. Use `NONE` if no spoken language.
* **DST** — Distributor (optional, for notable disc distributors). Values: `Criterion, BFI, Arrow, Shout, Indicator, Eureka, Kino, Second Sight, TT, VS, 88, Imprint, Umbrella, Severin, BU, Synapse, Scream, Mill Creek, WA, SPC, Universal, Paramount, Disney, Lionsgate, A24`
* **RLR** — Individual releaser/encoder tag. Optional, only in ENCODE patterns.
* **CRU** — Release group/crew tag. Mandatory. Use `NoGRP` if unknown.
* **RLS** — Release tag. Values: `PROPER, PROPER2, REPACK, REPACK2, REPACK3, DUBBED, SUBBED, INCOMPLETE`. Only when applicable.