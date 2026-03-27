# REDacted API Documentation

The JSON API provides an easily parse-able interface to Redacted. Below is the list of information available, the arguments that can be passed to it, and the format of the results.

* **Support:** Questions about the API can be answered in `#red-dev`. Bugs are best directed to the Bug Reports subforum.
* **Warning:** Using the API bestows upon you a certain level of trust and responsibility. Abusing or using this API for malicious purposes is a bannable offense and will not be taken lightly.

## Rate Limiting
Rate limits apply on a per-user basis, not IP. Upon exceeding the rate limit, you will receive an HTTP 429 error and a `Retry-After` header indicating the seconds remaining in your current API burst window.
* **Standard Login:** Maximum of 5 requests every 10 seconds.
* **API Key Login:** Maximum of 10 requests every 10 seconds.

## Authentication
To make requests to the Redacted API, you must be authenticated. Users can authenticate in two ways:
1. **Cookie:** Fetching a cookie through the login form at `https://redacted.sh/login.php`.
2. **API Key:** Generating an API key in user settings and sending an `Authorization: %apikey%` header with each request. (Recommended, especially for users with 2FA enabled).

> **Note:** Certain endpoints will be documented as being **API key only** to prevent session riding / CSRF. 

## Scope
When generating API keys, the scope of its access should be restricted to only grant access to the required areas of the site needed by the tool or application. This ensures that, even if your API key is compromised, its limited scope will prevent unauthorized access.

## Request & Response Format
* **Base URL Pattern:** `ajax.php?action=<ACTION>`
* **Standard Response:**
```json
{
  "status": "success",
  "response": {
    // Response data.
  }
}
```
*(If the request is invalid, or a problem occurs, the `status` will be "failure" and `response` is undefined).*

---

## Global Endpoints

### Index
`GET ajax.php?action=index`
Returns basic user info, stats, and the current API version.
* **Arguments:** None

```json
{
  "status": "success",
  "response": {
    "username": "dr4g0n",
    "id": 469,
    "authkey": "redacted",
    "passkey": "redacted",
    "api_version": "redacted-v2.0",
    "notifications": {
      "messages": 0,
      "notifications": 9000,
      "newAnnouncement": false,
      "newBlog": false
    },
    "userstats": {
      "uploaded": 585564424629,
      "downloaded": 177461229738,
      "ratio": 3.29,
      "requiredratio": 0.6,
      "class": "VIP"
    }
  }
}
```

---

## User Endpoints

### User Profile
`GET ajax.php?action=user`
* **Arguments:**
  * `id` - id of the user to display

### User Stats
`GET ajax.php?action=community_stats`
* **Arguments:**
  * `userid` - id of the user to display

### User Search
`GET ajax.php?action=usersearch`
* **Arguments:**
  * `search` - The search term.
  * `page` - page to display (default: 1)

### User Torrents
`GET ajax.php?action=user_torrents`
* **Arguments:**
  * `id` - request id
  * `type` - type of torrents to display. Options: `seeding`, `leeching`, `uploaded`, `snatched`
  * `limit` - number of results to display (default: 500)
  * `offset` - number of results to offset by (default: 0)

---

## Messages Endpoints

### Inbox
`GET ajax.php?action=inbox`
* **Arguments:**
  * `page` - page number to display (default: 1)
  * `type` - `inbox` or `sentbox` (default: inbox)
  * `sort` - set to `unread` to show unread messages first
  * `search` - filter messages by search string
  * `searchtype` - `subject`, `message`, `user`

### Conversation
`GET ajax.php?action=inbox&type=viewconv`
* **Arguments:**
  * `id` - id of the message/conversation to display

### Send PM
`POST ajax.php?action=send_pm`
**[API Key Authentication Required]**
* **Arguments:**
  * `toid` - user to send the PM to
  * `convid` - conversation to send the pm under (optional)
  * `subject` - subject of the conversation (required if convid is not specified)
  * `body` - body of the message

---

## Torrent & Media Endpoints

### Torrents Search
`GET ajax.php?action=browse`
* **Arguments:**
  * `searchstr` - string to search for
  * `page` - page to display (default: 1)
  * *(Advanced)*: `taglist`, `tags_type`, `order_by`, `order_way`, `filter_cat`, `freetorrent`, `vanityhouse`, `scene`, `haslog`, `releasetype`, `media`, `format`, `encoding`, `artistname`, `filelist`, `groupname`, `recordlabel`, `cataloguenumber`, `year`, `remastertitle`, `remasteryear`, `remasterrecordlabel`, `remastercataloguenumber`

### Torrent Details
`GET ajax.php?action=torrent`
* **Arguments:**
  * `id` - torrent's id
  * `hash` - torrent's hash (must be uppercase)

### Torrent Group Details
`GET ajax.php?action=torrentgroup`
* **Arguments:**
  * `id` - torrent's group id
  * `hash` - hash of a torrent in the torrent group (must be uppercase)

### Upload Torrent
`POST ajax.php?action=upload`
**[API Key Authentication Required]**
* **Arguments:**
  * `dryrun` - (bool) Only return derived info without actually uploading.
  * `file_input` - (file) `.torrent` file contents
  * `type` - (int) index of category (Music, Audiobook, etc)
  * `artists[]` - (str)
  * `importance[]` - (int) index of artist type (1-indexed: Main, Guest, Remixer, Composer, Conductor, DJ/Compiler, Producer, Arranger)
  * `title` - (str) Album title
  * `year` - (int) Album "Initial Year"
  * `releasetype` - (int) index of release type
  * `unknown` - (bool) Unknown Release
  * `remaster_year`, `remaster_title`, `remaster_record_label`, `remaster_catalogue_number`
  * `scene` - (bool) is this a scene release?
  * `format` - (str) MP3, FLAC, etc
  * `bitrate` - (str) 192, Lossless, Other, etc
  * `other_bitrate` - (str) bitrate if Other
  * `vbr` - (bool) other_bitrate is VBR
  * `logfiles[]` - (files) ripping log files
  * `vanity_house` - (bool)
  * `media` - (str) CD, DVD, Vinyl, etc
  * `tags` - (str)
  * `image` - (str) link to album art
  * `album_desc` - (str) Album description
  * `release_desc` - (str) Release (torrent) description
  * `desc` - (str) Description for non-music torrents
  * `groupid` - (int) torrent groupID (ie album) this belongs to
  * `requestid` - (int) requestID being filled
* **Response:**
```json
{
  "status": "success",
  "response": {
    "private": true,
    "source": "RED",
    "requestid": 0,
    "torrentid": 12345,
    "groupid": 54321,
    "newgroup": true
  }
}
```

### Download Torrent
`GET ajax.php?action=download`
**[API Key Authentication Required]**
* **Arguments:**
  * `id` - TorrentID to download.
  * `usetoken` - (optional) Default 0. Set to 1 to spend a FL token.
* **Response:** On success, a `.torrent` file with `content-type: application/x-bittorrent;`. On failure, standard JSON error.

### Torrent Edit
`POST ajax.php?action=torrentedit`
**[API Key Authentication Required]**
* **Arguments:**
  * `id` - torrent's id
  * *(Optional - at least one required)*: `format`, `media`, `bitrate`, `release_desc`, `remaster_year`, `remaster_title`, `remaster_record_label`, `remaster_catalogue_number`, `scene`, `unknown`

### Group Edit
`POST ajax.php?action=groupedit`
**[API Key Authentication Required]**
* **Arguments:**
  * `id` - group id
  * `summary` - Summary of edit changes
  * *(Optional - at least one required)*: `body`, `image`, `releasetype`, `groupeditnotes`

### Add Tag
`POST ajax.php?action=addtag`
**[API Key Authentication Required]**
* **Arguments:**
  * `groupid` - Torrent GroupID to add the tag to.
  * `tagname` - Tags to be added (comma separated).

### Torrent Log Files
`GET ajax.php?action=riplog`
* **Arguments:**
  * `id` - torrent's id
  * `logid` - logfile id

### Logchecker
`POST ajax.php?action=logchecker`
* **Arguments (Requires one):**
  * `pastelog` - (POST Parameter) The log string you would like checked.
  * `log` - (File Upload) The log file you would like checked.

### Top 10
`GET ajax.php?action=top10`
* **Arguments:**
  * `type` - `torrents`, `tags`, `users` (default: torrents)
  * `limit` - `10`, `100`, `250` (default: 10)

---

## Requests Endpoints

### Request Search
`GET ajax.php?action=requests`
* **Arguments:**
  * `search` - search term
  * `page` - page to display (default: 1)
  * `tags` - tags to search by (comma separated)
  * `tags_type` - 0 for any, 1 for match all
  * `show_filled` - true or false (default: false).
  * `filter_cat[]`, `releases[]`, `bitrates[]`, `formats[]`, `media[]`

### Request Details
`GET ajax.php?action=request`
* **Arguments:**
  * `id` - request id
  * `page` - page of the comments to display (default: last page)

### Request Fill
`POST ajax.php?action=requestfill`
**[API Key Authentication Required]**
* **Arguments (Either TorrentID or Link required):**
  * `requestid` - RequestID to fill.
  * `link` - Permalink to torrent which fills the request.
  * `torrentid` - TorrentID which fills the request.

---

## Other Endpoints

### Artist
`GET ajax.php?action=artist`
* **Arguments:**
  * `id` - artist's id
  * `artistname` - Artist's Name
  * `artistreleases` - if set, only include groups where artist is main.

### Similar Artists
`GET ajax.php?action=similar_artists`
* **Arguments:**
  * `id` - id of artist
  * `limit` - maximum number of results to return

### Bookmarks
`GET ajax.php?action=bookmarks`
* **Arguments:**
  * `type` - `torrents`, `artists` (default: torrents)

### Subscriptions
`GET ajax.php?action=subscriptions`
* **Arguments:**
  * `showunread` - 1 to show only unread, 0 for all (default: 1)

### Forums
* **Category View:** `GET ajax.php?action=forum&type=main`
* **Forum View:** `GET ajax.php?action=forum&type=viewforum&forumid=<Forum Id>` (Args: `forumid`, `page`)
* **Thread View:** `GET ajax.php?action=forum&type=viewthread&threadid=<Thread Id>&postid=<Post Id>` (Args: `threadid`, `postid`, `page`, `updatelastread`)

### Collages
* **Collage Details:** `GET ajax.php?action=collage&id=<Collage Id>`
  * *Optional Args:* `showonlygroups` (if set, does not return torrent info)
* **Adding Release to Collage:** `POST ajax.php?action=addtocollage` **[API Key Required]**
  * *Args:* `collageid` (GET), `groupids` (POST, comma separated string)

### Notifications
`GET ajax.php?action=notifications`
* **Arguments:**
  * `page` - page number to display (default: 1)

### Announcements
`GET ajax.php?action=announcements`
* **Arguments:**
  * `page` - (int) Default: 1
  * `perpage` - (int) Default: 5
  * `order_way` - (str) asc or desc. Default: desc
  * `order_by` - (str) id, title, body, time. Default: time

### Wiki
`GET ajax.php?action=wiki`
* **Arguments:**
  * `id` - id of wiki article
  * `name` - alias of wiki article

---

## Unofficial Projects that utilize the API
Many projects which utilize the API can be found in the Sandbox Forum. Examples include:
* **Python:** [Python] Sahel: Rate limit respecting, cache-optional basic Python API for Redacted
* **Go:** `https://github.com/autobrr/autobrr`
* **Go:** `https://github.com/s0up4200/redactedhook`

**Legacy/Vanilla what.cd API wrappers (Reference only, does not support API keys):**
* Python: `https://github.com/isaaczafuta/whatapi`
* Java: `https://github.com/Gwindow/WhatAPI`
* Ruby: `https://github.com/chasemgray/RubyGazelle`
* Javascript: `https://github.com/deoxxa/whatcd`
* C#: `https://github.com/frankston/WhatAPI`
* PHP: `https://github.com/Jleagle/php-gazelle`
* Go: `https://github.com/kdvh/whatapi`