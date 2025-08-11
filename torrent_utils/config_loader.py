import configparser
import sys
import os
import logging

# Define the master structure for the settings.ini file
# This includes all possible fields from all scripts to ensure a comprehensive template
CONFIG_STRUCTURE = {
    'DEFAULT': {
        '# Torrent Client Settings': '',
        'QBIT_HOST': '',
        'QBIT_USERNAME': '',
        'QBIT_PASSWORD': '',
        '# API Keys': '',
        'TMDB_API': '',
        'IMGBB_API': '',
        'PTPIMG_API': '',
        'CATBOX_HASH': '',
        '# Tracker APIs': '',
        'HUNO_API': '',
        'RED_API': '',
        '# Tracker URLs': '',
        'HUNO_URL': 'https://hawke.uno/api/torrents/upload',
        'RED_URL': 'https://redacted.ch',
        '# Paths': '',
        'SEEDING_DIR': '',
        '# Seedbox FTP Settings': '',
        'SEEDBOX_HOST': '',
        'SEEDBOX_PORT': '',
        'SEEDBOX_FTP_USER': '',
        'SEEDBOX_FTP_PASSWORD': '',
        '# Seedbox qBittorrent Settings': '',
        'SEEDBOX_QBIT_HOST': '',
        'SEEDBOX_QBIT_USER': '',
        'SEEDBOX_QBIT_PASSWORD': ''
    }
}

SETTINGS_FILE = 'settings.ini'

def load_settings():
    """
    Loads settings from settings.ini.
    If the file doesn't exist, it creates a template and exits.
    If it exists but is missing fields, it adds them and rewrites the file.
    Returns a configparser object.
    """
    # Handle non-existent file
    if not os.path.exists(SETTINGS_FILE):
        logging.info("No settings.ini file found. Generating a new one...")
        config = configparser.ConfigParser()
        config.read_dict(CONFIG_STRUCTURE)
        
        with open(SETTINGS_FILE, 'w') as configfile:
            configfile.write("# This is a configuration file for your torrent scripts.\n")
            configfile.write("# Please fill in the required fields before running the scripts again.\n")
            configfile.write("# Lines starting with '#' are comments and will be ignored.\n\n")
            config.write(configfile)

        sys.exit(f"{SETTINGS_FILE} has been generated. Please fill it out before running the script again.")

    # Load the existing user config to check for missing keys
    user_config = configparser.ConfigParser()
    user_config.read(SETTINGS_FILE)

    master_keys = set(k for k in CONFIG_STRUCTURE['DEFAULT'].keys() if not k.startswith('#'))
    user_keys = set(user_config['DEFAULT'].keys())

    # If all keys are present, no need to update the file
    if master_keys.issubset(user_keys):
        return user_config['DEFAULT']

    # If keys are missing, rebuild the file while preserving user values
    missing_keys = master_keys - user_keys
    logging.info(f"Updating settings.ini with missing fields: {', '.join(missing_keys)}")

    # Create a new config object from the master template to ensure correct order and comments
    updated_config = configparser.ConfigParser()
    updated_config.read_dict(CONFIG_STRUCTURE)

    # Copy the user's existing values into our new, complete config object
    for key, value in user_config['DEFAULT'].items():
        if updated_config.has_option('DEFAULT', key):
            updated_config.set('DEFAULT', key, value)

    # Write the updated, complete config back to the file
    with open(SETTINGS_FILE, 'w') as configfile:
        configfile.write("# This is a configuration file for your torrent scripts.\n")
        configfile.write("# Please fill in the required fields before running the scripts again.\n")
        configfile.write("# Lines starting with '#' are comments and will be ignored.\n\n")
        updated_config.write(configfile)

    # Return the new, complete settings object
    return updated_config['DEFAULT']


def validate_settings(settings, required_fields):
    """
    Validates that the required settings fields are present and not empty.
    
    Args:
        settings (configparser.SectionProxy): The settings object to validate.
        required_fields (list): A list of strings representing the required setting keys.
    
    Returns:
        bool: True if all required fields are valid, False otherwise.
    """
    missing_fields = []
    for field in required_fields:
        if field not in settings or not settings[field]:
            missing_fields.append(field)

    if missing_fields:
        logging.error(f"The following required settings are missing or empty in settings.ini: {', '.join(missing_fields)}")
        sys.exit("Please update your settings.ini file.")
    
    return True
