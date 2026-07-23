"""Constants for the Compal F3896LG integration."""

DOMAIN = "compal_f3896lg"

# Config entry keys
CONF_HOST = "host"
CONF_PASSWORD = "password"

# Default gateway address on a Ziggo LAN.
DEFAULT_HOST = "192.168.178.1"

# Manufacturer / model strings for the Home Assistant device registry entry.
# Liberty Global (Ziggo) ships the F3896LG built by Sagemcom (F@st 3896) and, in
# some batches, Compal — same REST API, same model number. The gateway's own
# reported model name is preferred at runtime; these are the fallbacks.
MANUFACTURER = "Sagemcom"
MODEL = "F3896LG"
