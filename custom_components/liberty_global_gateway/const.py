"""Constants for the Liberty Global cable gateway integration."""

DOMAIN = "liberty_global_gateway"

# Config entry keys
CONF_HOST = "host"
CONF_PASSWORD = "password"

# Fallback address offered in the manual config flow. Ziggo hands out
# 192.168.178.1; UPC / Virgin Media builds typically use 192.168.0.1. The flow
# prefers Home Assistant's actual default gateway and only falls back to this.
DEFAULT_HOST = "192.168.178.1"

# Manufacturer / model strings for the Home Assistant device registry entry.
# The gateway family is sold under several operator brands and built by two
# ODMs: Sagemcom (F3896LG / F3897LG / F5685LGB / F5685LGE) and Compal
# (CH7465LG). They share one LG-RDK firmware and one /rest/v1 API. The
# gateway's own reported manufacturer/model is preferred at runtime; these are
# only the fallbacks.
MANUFACTURER = "Sagemcom"
MODEL = "F3896LG"
