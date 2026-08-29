# Liberty Global Cable Gateway for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for the DOCSIS cable gateways Liberty Global
operators ship: the Ziggo SmartWifi modem in the Netherlands, the UPC and
Unitymedia Connect Box, the Virgin Media hubs, and the Sunrise and Yallo
equivalents. They run the same LG-RDK firmware and expose the same local admin
REST API. There is no cloud, and every poll stays on your LAN.

> Known by many names. If you searched for Ziggo modem, Ziggo SmartWifi,
> Sagemcom F@st 3896, Compal F3896LG, UPC Connect Box, Virgin Media Hub,
> Unitymedia Connect Box or Liberty Global cable gateway, this is the one.

## Supported hardware

| Model | ODM | Generation | Typically sold as |
|---|---|---|---|
| `F3896LG` | Sagemcom | mv2+ | Ziggo SmartWifi modem (NL), verified |
| `F3897LG` | Sagemcom | mv2+ | Ziggo / Liberty Global |
| `F5685LGB` | Sagemcom | mv3 | Liberty Global (DOCSIS 3.1, Wi-Fi 6) |
| `F5685LGE` | Sagemcom | mv3 | Liberty Global (DOCSIS 3.1, Wi-Fi 6) |
| `CH7465LG` | Compal | mv1 | UPC / Unitymedia Connect Box |

Operator brands the firmware ships skins for: Ziggo, UPC, Virgin Media,
Unitymedia, Sunrise, Yallo, Munro, Lumina, Grand Slam. The integration reads the
gateway's own branding, so the device shows up as e.g. *"Ziggo SmartWifi modem
(F3896LG)"*.

> Only the Sagemcom F3896LG on Ziggo, firmware `LG-RDK_12.13.16`, is verified
> against real hardware. The other models share the firmware and the API, so
> they should work, but nobody has confirmed it. Reports welcome. An endpoint a
> model lacks is skipped rather than breaking the poll.

_Unofficial, and not affiliated with Liberty Global, Ziggo, VodafoneZiggo, UPC,
Virgin Media, Sunrise, Unitymedia, Sagemcom or Compal. Use on your own gateway,
at your own risk._

## What you get

A single gateway device, named after your operator's own branding, with:

**Sensors**
- DOCSIS status (with DOCSIS version and service status attributes)
- Uptime (as a boot timestamp)
- Connected devices count
- Downstream power (min) and SNR (min)
- Upstream power (max)
- Downstream / upstream channel counts (with locked-channel counts as attributes)
- Corrected and uncorrected error counters
- T3 and T4 timeout counters, which indicate upstream line health
- Provisioned download / upload speed (your plan's rate caps, from the DOCSIS
  service flows)
- Firmware version and software-update status
- WAN IP address (public IPv4). WAN gateway, WAN IPv6, DHCP lease time and
  DNS servers ship as their own sensors, not as attributes of this one
- Gateway LAN IP, LAN DHCP pool range, and IPv6 delegated prefix
- Wi-Fi 2.4 GHz / 5 GHz SSID (with channel, width and security as attributes)
- Wi-Fi 2.4 GHz / 5 GHz channel numbers
- Last event, the newest cable-modem event-log line, with its timestamp,
  priority and total event count as attributes
- Port-forwarding rule count, DHCP reservation count, and active telephony lines
- MAC filter, port trigger and IP/port filter rule counts

**Binary sensors**
- Modem operational (connectivity)
- Registration complete and Downstream locked
- Baseline privacy (BPI+)
- Firewall, DMZ and UPnP state
- Smart Wi-Fi (band steering), and Guest Wi-Fi 2.4/5 GHz with the SSID as an attribute
- Bridge mode and DS-Lite (IPv4 over IPv6)
- Wi-Fi 2.4 GHz and 5 GHz up/down, and WPS on both bands

**Device trackers**
- One per device seen in the gateway's DHCP/association table, for presence
  detection (with IP, hostname, device type, interface, Wi-Fi band, RSSI, link
  speed, IPv6 and DHCP lease time as attributes).
- Like FRITZ!Box and UniFi, these trackers are disabled by default. Home
  Assistant enables the tracker for a device it already knows, meaning one whose
  MAC matches an existing device. Enable the others you want under
  **Settings**, **Devices & services**, **Entities**.

**Switches & controls**
- UPnP on/off, LED automatic brightness on/off, and LED brightness from 0 to
  100. Nothing here can drop your connection, so there are no Wi-Fi radio or
  bridge-mode toggles.

**Button**
- Reboot gateway. This drops the WAN for a minute or two, so it is deliberate.

## How it handles the single-session gateway

The gateway allows **exactly one authenticated session**. This integration logs
in, reads everything in one burst, and then **logs out** (`DELETE
/user/<id>/token/<token>`) every polling cycle (every 5 minutes), so the
gateway's single session is freed immediately and its web UI stays usable
between polls. Successful logins never count toward the lockout, so the regular
cadence is safe.

If the web UI is open (holding the session) when a poll runs, the integration
replays the last-known values instead of flapping every entity to *unavailable*.
That replay is bounded at two consecutive cycles, so a web UI left open all
afternoon makes the entities unavailable rather than serving hours-old readings
as if they were current. Entity commands (reboot, the switches, LED brightness)
take the same session lock as the poll, so a button press can never revoke the
token a poll is holding.

A lockout is a cooldown of a few minutes that clears by itself, so it is treated
as a temporary update failure and retried. It does not ask you to re-enter your
password, because the stored one is still correct.

Built on the [`liberty-global-gateway`](https://github.com/AboveColin/liberty-global-gateway)
Python library.

## Installation

Requires Home Assistant **2025.2.0** or newer: the config flow imports
`homeassistant.helpers.service_info.ssdp`, which does not exist before that
release.

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/AboveColin/HA-Liberty-Global-Gateway` as an **Integration**.
3. Install **Liberty Global Cable Gateway**, then restart Home Assistant.

### Manual

Copy `custom_components/liberty_global_gateway` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

### Automatic discovery

If UPnP is enabled on the gateway, Home Assistant finds it over SSDP and offers
it under **Settings**, **Devices & services**. You only enter the admin
password. Before offering it, the integration checks an unauthenticated
identification endpoint to confirm the device is one of these gateways, so other
UPnP routers on the network are ignored.

Some operator builds ship with UPnP off. Add the gateway manually there.

### Manual

**Settings → Devices & services → Add integration → Liberty Global Cable
Gateway.**

- Gateway address, pre-filled with an address that answers on your network.
  That is `192.168.178.1` on Ziggo and `192.168.0.1` on UPC and Virgin Media.
- Admin password, printed on the sticker on the gateway unless you changed it.

> Close the gateway's web UI before adding it. The gateway allows one session at
> a time.

The admin certificate is self-signed, so TLS verification is off by default.

## Notes

- Local polling every 5 minutes. No data leaves your network.
- After a handful of wrong passwords the gateway locks out login attempts for a
  few minutes. The setup form reports the lockout instead of hammering it.
- The download and upload sensors report the DOCSIS service-flow rate caps for
  your plan. That is the provisioned speed, not a throughput test.

## License

MIT, see [LICENSE](LICENSE).
