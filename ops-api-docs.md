# Orpheus API Documentation

**From:** itismadness  
**To:** Developers  
**Date:** 2021-08-21  
**Subject:** Orpheus Development Papers #7 - API Documentation  
**Version:** 2 (2024-11-06)  

The JSON API provides an easily parseable interface to Gazelle. The API comes standard in public Gazelle and works out of the box. Below is the list of information available, the arguments that can be passed to it, and the format of the results.

## Authentication
You must be logged in to use the API, which can be done in two ways:

1. **Website Authentication and Cookie**
The default method of authentication is by sending a `POST` request to `/login.php` with your username and password which will respond with a cookie that is then used for subsequent requests to the API.

2. **API Token**
After generating a token on your user profile, you can use it by sending a request with the header `Authorization: token ${api_token}` or `Authorization: ${api_token}` (deprecated).
*NOTE: For the API token, please be aware we heavily discourage people from using the latter form and that it only exists for the sake of interoperability and may go away in the future.*

## Rate Limits & Usage
Questions about the API can be answered in `#develop`.

> **Warning:** Using the API bestows upon you a certain level of trust and responsibility. Abusing or using this API for malicious purposes is a bannable offense and will not be taken lightly.
> 
> **Refrain from making more than five (5) requests every ten (10) seconds.**

---

## Global API Format

All request URLs are in the form: `ajax.php?action=<ACTION>`

All the JSON returned is in the form:

```json
{
    "status": "success",
    "response": {
        // Response data.
    },
    "info": {
        "source": "Gazelle Dev",
        "version": 1
    }
}
```

If the request is invalid, or a problem occurs, the `status` will be `failure`. In this case the value of `response` is `undefined`.

---

## 1. Global Endpoints

### Index
`GET ajax.php?action=index`

* **Arguments:** None

**Response format:**
```json
{
    "status": "success",
    "response": {
        "username": "dr4g0n",
        "id": 469,
        "authkey": "redacted",
        "passkey": "redacted",
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
            "bonusPoints": 220903,
            "bonusPointsPerHour": 1.28,
            "class": "VIP"
        }
    }
}
```

### Top 10
`GET ajax.php?action=top10`

* **Arguments:**
  * `type` - Specifies the type of top 10 list to retrieve:
    * `torrents` (Default)
    * `users`
    * `tags`
  * `details` - Category for the selected `type`. `all` lists all categories (Default). 
    * When `type` = `torrents`: `day`, `week`, `month`, `year`, `overall`, `snatched`, `data`, `seeded`
    * When `type` = `users`: `ul`, `dl`, `numul`, `uls`, `dls`
    * When `type` = `tags`: `ut`, `ur`, `v`
  * `limit` - The maximum number of results to return per category. Must be one of `10` (default), `100` or `250`. When `type`="torrents" and `details`="all", only `limit`="10" is permitted.

**Response format (Torrents example):**
```json
{
    "status": "success",
    "response": [
        {
            "caption": "Most Active Torrents Uploaded in the Past Day",
            "tag": "day",
            "limit": 10,
            "results": [
                {
                    "torrentId": 30194226,
                    "groupId": 72268716,
                    "artist": "2 Chainz",
                    "groupName": "Based on a T.R.U. Story",
                    "groupCategory": 0,
                    "groupYear": 2012,
                    "remasterTitle": "Deluxe Edition",
                    "format": "MP3",
                    "encoding": "V0 (VBR)",
                    "hasLog": false,
                    "hasCue": false,
                    "media": "CD",
                    "scene": true,
                    "year": 2012,
                    "tags": ["hip.hop"],
                    "snatched": 135,
                    "seeders": 127,
                    "leechers": 5,
                    "data": 17242225550
                }
            ]
        }
    ]
}
```

### Announcements
`GET ajax.php?action=announcements`

**Response format:**
```json
{
    "status": "success",
    "response": {
        "announcements": [
            {
                "newsId": 263,
                "title": "An update! A new forum, new features and more.",
                "body": "Much has happened recently!...",
                "newsTime": "2012-11-14 03:14:12"
            }
        ],
        "blogPosts": []
    }
}
```

---

## 2. User & Profile Endpoints

### User Profile
`GET ajax.php?action=user`

* **Arguments:**
  * `id` - id of the user to display

**Response format:**
```json
{
    "status": "success",
    "response": {
        "username": "dr4g0n",
        "avatar": "http://v0lu.me/rubadubdub.png",
        "isFriend": false,
        "profileText": "",
        "stats": {
            "joinedDate": "2007-10-28 14:26:12",
            "lastAccess": "2012-08-09 00:17:52",
            "uploaded": 585564424629,
            "downloaded": 177461229738,
            "ratio": 3.3,
            "requiredRatio": 0.6
        },
        "ranks": {
            "uploaded": 98,
            "downloaded": 95,
            "uploads": 85,
            "requests": 0,
            "bounty": 79,
            "posts": 98,
            "artists": 0,
            "overall": 85
        },
        "personal": {
            "class": "VIP",
            "paranoia": 0,
            "paranoiaText": "Off",
            "donor": true,
            "warned": false,
            "enabled": true,
            "passkey": "redacted"
        },
        "community": {
            "posts": 863,
            "torrentComments": 13,
            "collagesStarted": 0,
            "collagesContrib": 0,
            "requestsFilled": 0,
            "requestsVoted": 13,
            "perfectFlacs": 2,
            "uploaded": 29,
            "groups": 14,
            "seeding": 309,
            "leeching": 0,
            "snatched": 678,
            "invited": 7
        }
    }
}
```

### User Search
`GET ajax.php?action=usersearch`

* **Arguments:**
  * `search` - The search term.
  * `page` - page to display (default: 1)

**Response format:**
```json
{
    "status": "success",
    "response": {
        "currentPage": 1,
        "pages": 1,
        "results": [
            {
                "userId": 469,
                "username": "dr4g0n",
                "donor": true,
                "warned": false,
                "enabled": true,
                "class": "VIP"
            }
        ]
    }
}
```

### User Torrents
`GET ajax.php?action=user_torrents`

*NOTE: Must be the uploader of the torrent or moderator to view.*

* **Arguments:**
  * `userid` - The user id to get torrents for (can also use `id`)
  * `type` - Type of torrents to display (`downloaded`, `leeching`, `seeding`, `snatched`, `snatched-unseeded`, `uploaded`, `uploaded-unseeded`)
  * `limit` - Number of results to display (default: 500)
  * `offset` - Number of results to offset by (default: 0)
  * `page` - Page of results to show (default: 1)
  * *Note: Provide only one of `offset` or `page`.*

**Response format:**
```json
{
  "status": "success",
  "response": {
    "uploaded": [
        {
            "groupId": 1,
            "torrentId": 1,
            "name": "Foo",
            "torrentSize": 12345,
            "artistId": 1,
            "artistName": "Bar",
            "artists": {
                "artists": [
                    {
                        "id": 1,
                        "aliasid": 1,
                        "name": "Bar"
                    }
                ]
            }
        }
    ],
    "total": 1
  },
  "info": {
    "source": "Gazelle Dev",
    "version": 1
  }
}
```

---

## 3. Torrents & Media Endpoints

### Torrent Search
`GET ajax.php?action=browse`

* **Arguments:**
  * `searchstr` - string to search for
  * `page` - page to display (default: 1)
  * `taglist`, `tags_type`, `order_by`, `order_way`, `filter_cat`, `freetorrent`, `vanityhouse`, `scene`, `haslog`, `releasetype`, `media`, `format`, `encoding`, `artistname`, `filelist`, `groupname`, `recordlabel`, `cataloguenumber`, `year`, `remastertitle`, `remasteryear`, `remasterrecordlabel`, `remastercataloguenumber` - as in advanced search

### Torrent Group
`GET ajax.php?action=torrentgroup`

* **Arguments:**
  * `id` - torrent's group id
  * `hash` - hash of a torrent in the torrent group (must be uppercase)

### Torrent Details
`GET ajax.php?action=torrent`

* **Arguments:**
  * `id` - torrent's id
  * `hash` - torrent's hash (must be uppercase)

### Upload Torrent
`POST ajax.php?action=upload`

*NOTE: Requires using the API token or authkey. Use 0 and 1 for boolean fields. If using `groupid`, you may leave group details (e.g. `title`, `year`) out.*

* **Arguments:**
  * `file_input` - (file) .torrent file contents
  * `groupid` - (int) torrent groupID (ie album) this belongs to
  * `type` - (int) Category to use (0 - Music, 1 - Applications, etc.)
  * `artists[]` - (str) name of artist, provide multiple time per artist
  * `importance[]` - (int) index of artist type (Main, Guest, Composer, etc.)
  * `title` - (str) Album title
  * `year` - (int) Album "Initial Year"
  * `record_label` - (str) Album record label
  * `releasetype` - (int) index of release type
  * `unknown` - (bool) Unknown Release
  * `remaster` - (bool) Is a remaster or not
  * `remaster_year` - (int) Edition year
  * `remaster_title` - (str) Edition title
  * `remaster_record_label` - (str) Edition record label
  * `remaster_catalogue_number` - (str) Edition catalog number
  * `scene` - (bool) is this a scene release?
  * `media` - (str) CD, WEB, DVD, etc.
  * `format` - (str) MP3, FLAC, etc
  * `bitrate` - (str) 192, Lossless, Other, etc
  * `other_bitrate` - (str) bitrate if bitrate is Other
  * `vbr` - (bool) other_bitrate is VBR
  * `logfiles[]` - (files) ripping log files
  * `extra_file_#` - (file) extra .torrent file contents, # is 1 to 5
  * `extra_format[]`, `extra_bitrate[]`, `extra_release_desc[]`
  * `vanity_house` - (bool) is this a Vanity House release?
  * `tags` - (str) comma separated list of tags for album
  * `image` - (str) link to album art
  * `album_desc` - (str) Album description
  * `release_desc` - (str) Release (torrent) description
  * `desc` - (str) Description for non-music torrents
  * `requestid` - (int) requestID being filled

**Response format:**
```json
{
    "status": "success",
    "response": {
        "groupId": 384,
        "torrentId": 526,
        "private": true,
        "source": true,
        "fillRequest": {
            "requestId": 1,
            "torrentId": 526,
            "fillerId": 1,
            "fillerName": "hermes",
            "bounty": 1232452
        },
        "warnings": [
            "non-critical html error messages"
        ]
    }
}
```

### Download
`GET ajax.php?action=download`

*NOTE: Requires using the API token.*

* **Arguments:**
  * `id` - torrent id
  * `usetoken` - use FL token to download torrent (default: false)
  * `ssl` - force https (optional, defaults to user setting)

* **Response format:** Either a raw BEncoded torrent file with `application/x-bittorrent` content-type or regular JSON error format if invalid parameters.

### Add Tag
`POST ajax.php?action=add_tag` or `ajax.php?action=addtag`

*NOTE: Must use either API token or `$_POST['authkey']`*

* **Arguments:**
  * `groupid` - group id
  * `tagname` - comma separated list of tags to add to group

### Add Log
`POST ajax.php?action=add_log`

*NOTE: Must be the uploader of the torrent or moderator to add logs.*

* **Arguments:**
  * `id` - (GET) ID of torrent to add logs to
  * `logfiles[]` - (POST file) ripping log files

### Logchecker
`POST ajax.php?action=logchecker`

* **Arguments:** (Provide only one)
  * `log` - uploaded log file through `multipart/form-data`
  * `pastelog` - log submitted via regular `$_POST`

### Better
`GET ajax.php?action=better`

* **Arguments:**
  * `method` (required) - `single` (single-seeded), `transcode` (missing transcodes)
  * *(If `method=transcode`)*:
    * `search` - search term
    * `filter` - limit torrents based on user's torrents (`any`, `seeding`, `snatched`, `uploaded`)
    * `target` - missing transcodes to list (`v0`, `320`, `all`, `any`)

---

## 4. Requests Endpoints

### Requests Search
`GET ajax.php?action=requests`

* **Arguments:**
  * `search` - search term
  * `page` - page to display (default: 1)
  * `tags` - tags to search by (comma separated)
  * `tags_type` - `0` for any, `1` for match all
  * `show_filled` - Include filled requests in results - `true` or `false` (default: false).
  * `filter_cat[]`, `releases[]`, `bitrates[]`, `formats[]`, `media[]`

### Request Details
`GET ajax.php?action=request`

* **Arguments:**
  * `id` - request id
  * `page` - page of the comments to display (default: last page)

### Request Fill
`POST ajax.php?action=request_fill` or `ajax.php?action=requestfill`

* **Arguments:**
  * `requestid` - Request Id
  * `torrentid` - Torrent Id
  * `link` - Permalink to torrent on site
  * `user` - Username to use for request fill (mod+ only)
  * *Note: Either `torrentid` or `link` must be used.*

---

## 5. Metadata Endpoints

### Artist
`GET ajax.php?action=artist`

* **Arguments:**
  * `id` - artist's id
  * `artistname` - Artist's Name
  * `artistreleases` - if set, only include groups where the artist is the main artist.

### Similar Artists
`GET ajax.php?action=similar_artists`

* **Arguments:**
  * `id` - id of artist
  * `limit` - maximum number of results to return (fewer might be returned)

### Collages
`GET ajax.php?action=collage`

* **Arguments:**
  * `id` - collage's id
  * `page` - page number for torrent groups (default: 1)

### Bookmarks
`GET ajax.php?action=bookmarks`

* **Arguments:**
  * `type` - one of `torrents`, `artists` (default: torrents)

---

## 6. Communication Endpoints

### Inbox
`GET ajax.php?action=inbox`

* **Arguments:**
  * `page` - page number to display (default: 1)
  * `type` - `inbox` or `sentbox` (default: inbox)
  * `sort` - if set to `unread` then unread messages come first
  * `search` - filter messages by search string
  * `searchtype` - `subject`, `message`, `user`

### Conversation
`GET ajax.php?action=inbox&type=viewconv`

* **Arguments:**
  * `id` - id of the message to display

### Subscriptions
`GET ajax.php?action=subscriptions`

* **Arguments:**
  * `showunread` - `1` to show only unread, `0` for all subscriptions (default: 1)

### Notifications
`GET ajax.php?action=notifications`

* **Arguments:**
  * `page` - page number to display (default: 1)

**Response format:**
```json
{
    "status": "success",
    "response": {
        "currentPages": 1,
        "pages": 105,
        "numNew": 0,
        "results": [
            {
                "torrentId": 30194383,
                "groupId": 71944561,
                "groupName": "You Are a Tourist",
                "torrentTags": "alternative indie",
                "unread": false
            }
        ]
    }
}
```

---

## 7. Forums Endpoints

### Category View
`GET ajax.php?action=forum&type=main`
* **Response:** Categories and recent topics.

### Forum View
`GET ajax.php?action=forum&type=viewforum`

* **Arguments:**
  * `forumid` - id of the forum to display
  * `page` - the page to display (default: 1)

### Thread View
`GET ajax.php?action=forum&type=viewthread`

* **Arguments:**
  * `threadid` - id of the thread to display
  * `postid` - response will be the page including the post with this id
  * `page` - page to display (default: 1)
  * `updatelastread` - set to 1 to not update the last read id (default: 0)

---

## Unofficial projects that utilize the API
- Python - [https://github.com/cohena/pygazelle](https://github.com/cohena/pygazelle)
- Python - [https://github.com/isaaczafuta/whatapi](https://github.com/isaaczafuta/whatapi)
- Java - [https://github.com/Gwindow/WhatAPI](https://github.com/Gwindow/WhatAPI)
- Ruby - [https://github.com/chasemgray/RubyGazelle](https://github.com/chasemgray/RubyGazelle)
- Javascript - [https://github.com/deoxxa/whatcd](https://github.com/deoxxa/whatcd)
- C# - [https://github.com/frankston/WhatAPI](https://github.com/frankston/WhatAPI)
- PHP - [https://github.com/GLaDOSDan/whatcd-php](https://github.com/GLaDOSDan/whatcd-php)
- PHP - [https://github.com/Jleagle/php-gazelle](https://github.com/Jleagle/php-gazelle)
- Go - [https://github.com/kdvh/whatapi](https://github.com/kdvh/whatapi)