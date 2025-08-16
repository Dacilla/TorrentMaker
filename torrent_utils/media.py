import logging
import guessit
import json
import requests
import os
import re
from pymediainfo import MediaInfo
from datetime import datetime
from babel import Locale

# These are still needed for now, but more logic will be moved from them.
from .helpers import get_tmdb_id, get_season, get_episode

class MediaFile:
    """A base class representing a generic media file."""

    def __init__(self, file_path: str):
        if not file_path:
            raise ValueError("File path cannot be empty.")
        self.path = file_path
        self.filename = os.path.basename(file_path)
        logging.info(f"Initializing MediaFile for: {self.filename}")
        self.media_info = self._parse_media_info()
        self.guessit_info = guessit.guessit(self.filename)
        logging.debug(f"Guessit Info: {self.guessit_info}")

    def _parse_media_info(self) -> dict:
        try:
            media_info_str = MediaInfo.parse(self.path, output="JSON")
            return json.loads(media_info_str)
        except Exception as e:
            logging.error(f"Could not parse MediaInfo for {self.filename}: {e}")
            return {}

    @property
    def video_track(self) -> dict:
        if self.media_info and 'track' in self.media_info.get('media', {}):
            return next((t for t in self.media_info['media']['track'] if t.get('@type') == 'Video'), {})
        return {}

    @property
    def audio_track(self) -> dict:
        if self.media_info and 'track' in self.media_info.get('media', {}):
            return next((t for t in self.media_info['media']['track'] if t.get('@type') == 'Audio'), {})
        return {}
        
    def get_resolution(self) -> str:
        """Determines the video resolution with more detailed logic."""
        if not self.video_track: return "Unknown"
        
        width = self.video_track.get('Width')
        height = self.video_track.get('Height')
        frame_rate = self.video_track.get('FrameRate')

        if not width or not height: return "Unknown"

        width_to_height_dict = {"720": "576", "960": "540", "1280": "720", "1920": "1080", "4096": "2160", "3840": "2160", "692": "480", "1024": "576"}
        acceptedHeights = ['576', '480', '360', '240', '720', '1080', '1440', '2160']
        
        width_str = str(width)
        height_str = str(height)

        if width_str in width_to_height_dict:
            height_str = width_to_height_dict[width_str]
            if height_str == "576" and frame_rate and "29" in str(frame_rate):
                logging.info("NTSC detected. Changed resolution to 480p")
                height_str = "480"
            return f"{height_str}p"

        if height_str in acceptedHeights:
            resolution = f"{height_str}p"
            if "Interlaced" in str(self.media_info):
                resolution = resolution.replace("p", "i")
            return resolution

        logging.warning(f"Could not determine standard resolution for {width}x{height}. Using height.")
        return f"{height_str}p"


    def get_video_codec(self, source: str) -> str:
        """Determines the video codec based on MediaInfo, filename and source."""
        if not self.video_track: return "H264" # Default
        
        video_format = self.video_track.get('Format', '')
        file_lower = self.filename.lower()
        source_lower = source.lower() if source else ""

        if 'HEVC' in video_format:
            if 'remux' in source_lower: return 'HEVC'
            if 'h265' in file_lower or 'hevc' in file_lower: return 'H265'
            return "x265"
        if "VC-1" in video_format: return "VC-1"
        if "V_MPEG2" in self.video_track.get('CodecID', ''): return "MPEG-2"
        if 'remux' in source_lower: return "AVC"
        if 'x264' in file_lower: return "x264"
        return "H264"

    def get_audio_info(self) -> str:
        """Determines the audio format and channels from the primary audio track."""
        audio_track = self.audio_track
        if not audio_track:
            logging.warning("No audio track found!")
            return ""

        # Codec mapping
        codecsDict = {
            "E-AC-3": "EAC3", "MLP FBA": "TrueHD", "DTS": "DTS",
            "AAC": "AAC", "PCM": "PCM", "AC-3": "DD",
            "FLAC": "FLAC", "Opus": "OPUS"
        }
        
        audio_format = None

        # Check for commercial format names first
        if 'Format_Commercial_IfAny' in audio_track:
            commercialFormat = audio_track['Format_Commercial_IfAny']
            if "Dolby Digital Plus" in commercialFormat: audio_format = "DDP"
            elif "Dolby Digital" in commercialFormat: audio_format = "DD"
            elif "TrueHD" in commercialFormat: audio_format = "TrueHD"
            elif "DTS-HD Master Audio" in commercialFormat: audio_format = "DTS-HD MA"
            elif "DTS-HD High Resolution Audio" in commercialFormat: audio_format = "DTS-HD HR"
            elif "DTS-ES" in commercialFormat: audio_format = "DTS-ES"
            elif "DTS" in commercialFormat: audio_format = "DTS"
            
            if audio_format and 'Atmos' in commercialFormat:
                audio_format += " Atmos"

        # Fallback to technical format names
        if audio_format is None:
            format_key = audio_track.get('Format')
            if format_key in codecsDict:
                audio_format = codecsDict[format_key]
            elif format_key == "MPEG Audio" and audio_track.get('Format_Profile') == 'Layer 3':
                audio_format = "MP3"
            elif audio_track.get('Format_Settings_Endianness') == "Little":
                audio_format = "LPCM"
            elif 'Vorbis' in str(format_key):
                audio_format = "Vorbis"

        if audio_format is None:
            logging.error("Could not determine audio format.")
            audio_format = "Audio"

        # Determine channels
        channels_num_str = audio_track.get('Channels', '0')
        try:
            channels_num = int(channels_num_str)
            channel_layout = audio_track.get('ChannelLayout', '')
            
            if "LFE" in channel_layout:
                main_channels = channels_num - 1
                channel_str = f"{main_channels}.1"
            else:
                channel_str = f"{channels_num}.0"
        except (ValueError, TypeError):
            channel_str = f"{channels_num_str}.0"
            
        return f"{audio_format} {channel_str}"

    def get_colour_space(self) -> str:
        """Determines the color space (SDR, HDR, etc.)."""
        if "HDR" not in str(self.video_track): return "SDR"
        
        hdr_format = self.video_track.get('HDR_Format', '')
        hdr_compat = self.video_track.get('HDR_Format_Compatibility', '')

        if "Dolby Vision" in hdr_format:
            if "HDR10+" in hdr_compat: return "DV HDR10+"
            if "HDR10" in hdr_compat: return "DV HDR"
            return "DV"
        if "HDR10+" in hdr_format: return "HDR10+"
        return "HDR"

    def get_language_name(self) -> str:
        """Gets the display name of the audio language."""
        if not self.audio_track or 'Language' not in self.audio_track:
            return input("No language found. Please input language:\n")
        
        try:
            locale = Locale(self.audio_track['Language'])
            return locale.get_display_name('en')
        except Exception:
            return 'Unknown'


class Movie(MediaFile):
    """Represents a movie file."""
    
    def __init__(self, file_path: str, tmdb_api_key: str, tmdb_id: int = None):
        super().__init__(file_path)
        self.tmdb_api_key = tmdb_api_key
        self.tmdb_id = tmdb_id
        self.metadata = self.fetch_metadata()

    def fetch_metadata(self) -> dict:
        if not self.tmdb_id:
            logging.info("Attempting to find TMDB ID for movie...")
            title_to_search = self.guessit_info.get('title', '')
            self.tmdb_id = get_tmdb_id(title_to_search, self.tmdb_api_key, isMovie=True)
        
        if not self.tmdb_id:
            logging.error("Could not determine TMDB ID for movie.")
            return {}

        url = f'https://api.themoviedb.org/3/movie/{self.tmdb_id}?api_key={self.tmdb_api_key}'
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to fetch TMDB data: {e}")
            return {}

    def generate_name(self, source: str, group: str, huno_format: bool) -> str:
        """Generates a standardized filename for the movie."""
        if not self.metadata: return ""

        title = self.metadata.get('title', 'Unknown Movie').replace(':', '')
        year = self.metadata.get('release_date', '0000')[:4]
        resolution = self.get_resolution()
        video_codec = self.get_video_codec(source)
        audio = self.get_audio_info()
        container = self.guessit_info.get('container', 'mkv')

        if huno_format:
            colour_space = self.get_colour_space()
            language = self.get_language_name()
            base_name = f"{title} ({year})"
            details = f"{resolution} {source} {video_codec} {colour_space} {audio} {language} - {group}"
            filename = f"{base_name} ({details}).{container}"
        else:
            if video_codec == "H264": video_codec = "H.264"
            elif video_codec == "H265": video_codec = "H.265"
            parts = [title, year, resolution, source, audio.replace(' ', ''), video_codec]
            filename = '.'.join(filter(None, parts)) + f"-{group}.{container}"
            filename = filename.replace(' ', '.')
        
        return re.sub(r'[\'é]', '', filename).replace('..', '.').replace('--', '-')


class TVShow(MediaFile):
    """Represents a TV show episode file."""

    def __init__(self, file_path: str, tmdb_api_key: str, tmdb_id: int = None):
        super().__init__(file_path)
        self.tmdb_api_key = tmdb_api_key
        self.tmdb_id = tmdb_id
        self.metadata = self.fetch_metadata()

    def fetch_metadata(self) -> dict:
        if not self.tmdb_id:
            logging.info("Attempting to find TMDB ID for TV show...")
            title_to_search = self.guessit_info.get('title', '')
            self.tmdb_id = get_tmdb_id(title_to_search, self.tmdb_api_key, isMovie=False)

        if not self.tmdb_id:
            logging.error("Could not determine TMDB ID for TV show.")
            return {}
            
        url = f'https://api.themoviedb.org/3/tv/{self.tmdb_id}?api_key={self.tmdb_api_key}'
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to fetch TMDB data: {e}")
            return {}

    def generate_name(self, source: str, group: str, huno_format: bool) -> str:
        """Generates a standardized filename for the TV episode."""
        if not self.metadata: return ""

        show_name = self.metadata.get('name', 'Unknown Show').replace(':', '')
        year = self.metadata.get('first_air_date', '0000')[:4]
        resolution = self.get_resolution()
        video_codec = self.get_video_codec(source)
        audio = self.get_audio_info()
        container = self.guessit_info.get('container', 'mkv')
        
        season = get_season(self.filename)
        episode = "E" + get_episode(self.filename)
        episode_title = self.guessit_info.get('episode_title')
        episode_num = f"{season}{episode}"
        if episode_title:
            episode_num += f" - {episode_title}"

        if huno_format:
            colour_space = self.get_colour_space()
            language = self.get_language_name()
            base_name = f"{show_name} ({year}) - {episode_num}"
            details = f"{resolution} {source} {video_codec} {colour_space} {audio} {language} - {group}"
            filename = f"{base_name} ({details}).{container}"
        else:
            if video_codec == "H264": video_codec = "H.264"
            elif video_codec == "H265": video_codec = "H.265"
            parts = [show_name, year, episode_num, resolution, source, audio.replace(' ', ''), video_codec]
            filename = '.'.join(filter(None, parts)) + f"-{group}.{container}"
            filename = filename.replace(' ', '.')

        return re.sub(r'[\'é]', '', filename).replace('..', '.').replace('--', '-')
