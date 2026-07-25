# Liberty Global Cable Gateway — Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for the DOCSIS cable gateways that **Liberty Global**
operators ship — the **Ziggo SmartWifi modem** (NL), the **UPC / Unitymedia
Connect Box**, **Virgin Media** hubs, and the Sunrise / Yallo equivalents. They
all run the same LG-RDK firmware and expose the same local admin REST API — no
cloud, all polling stays on your LAN.

> **Known by many names.** If you searched for *Ziggo modem*, *Ziggo SmartWifi*,
> *Sagemcom F@st 3896*, *Compal F3896LG*, *UPC Connect Box*, *Virgin Media Hub*,
> *Unitymedia Connect Box* or *Liberty Global cable gateway* — this is the one.

## Supported hardware

| Model | ODM | Generation | Typically sold as |
|---|---|---|---|
| `F3896LG` | Sagemcom | mv2+ | Ziggo SmartWifi modem (NL) — **verified** |
| `F3897LG` | Sagemcom | mv2+ | Ziggo / Liberty Global |
| `F5685LGB` | Sagemcom | mv3 | Liberty Global (DOCSIS 3.1, Wi-Fi 6) |
| `F5685LGE` | Sagemcom | mv3 | Liberty Global (DOCSIS 3.1, Wi-Fi 6) |
| `CH7465LG` | Compal | mv1 | UPC / Unitymedia Connect Box |

Operator brands the firmware ships skins for: Ziggo, UPC, Virgin Media,
Unitymedia, Sunrise, Yallo, Munro, Lumina, Grand Slam. The integration reads the
gateway's own branding, so the device shows up as e.g. *"Ziggo SmartWifi modem
(F3896LG)"*.

> Only the **Sagemcom F3896LG** (Ziggo, firmware `LG-RDK_12.13.16`) is verified
> against real hardware. The other models share the firmware and API, so they are
> expected to work but are unverified — reports welcome. Endpoints a model lacks
> are skipped rather than breaking the poll.

_Unofficial and not affiliated with, endorsed by, or connected to Liberty Global,
Ziggo, VodafoneZiggo, UPC, Virgin Media, Sunrise, Unitymedia, Sagemcom or Compal.
Use on your own gateway at your own risk._

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
- **T3 and T4 timeout counters** (upstream line-health indicators)
- Provisioned download / upload speed (your plan's rate caps, from the DOCSIS
  service flows)
- Firmware version and **software-update status**
- **WAN IP address** (public IPv4, with gateway, DNS, IPv6 and lease as attributes)
- Gateway LAN IP and IPv6 delegated prefix
- Wi-Fi 2.4 GHz / 5 GHz SSID (with channel, width and security as attributes)
- **Last event** — the newest cable-modem event-log line, with its timestamp,
  priority and total event count as attributes
- Port-forwarding rule count, DHCP reservation count, and active telephony lines

**Binary sensors**
- Modem operational (connectivity)
- Registration complete and Downstream locked
- Baseline privacy (BPI+)
- **Firewall**, **DMZ** and **UPnP** state (security at a glance)
- **Smart Wi-Fi** (band steering); Guest Wi-Fi 2.4/5 GHz (SSID as attribute)
- Bridge mode
- Wi-Fi 2.4 GHz and Wi-Fi 5 GHz up/down

**Device trackers**
- One per device seen in the gateway's DHCP/association table, for presence
  detection (with IP, hostname, device type, interface, Wi-Fi band, RSSI, link
  speed, IPv6 and DHCP lease time as attributes).
- Like other router integrations (FRITZ!Box, UniFi, …), these trackers are
  **disabled by default**. Home Assistant automatically enables a tracker for a
  device it already knows (one whose MAC matches an existing device); enable any
  others you want to track under **Settings → Devices & services → Entities**.

**Switches & controls**
- **UPnP** on/off, **LED automatic brightness** on/off, and **LED brightness**
  (0-100). Connectivity-safe only — no Wi-Fi radio or bridge-mode toggles.

**Button**
- Reboot gateway (drops the WAN for a minute or two — a deliberate action).

## How it handles the single-session gateway

The gateway allows **exactly one authenticated session**. This integration logs
in, reads everything in one burst, and then **logs out** (`DELETE
/user/<id>/token/<token>`) every polling cycle (every 5 minutes), so the
gateway's single session is freed immediately and its web UI stays usable
between polls. Successful logins never count toward the lockout, so the regular
cadence is safe. If the web UI is open (holding the session) when a poll runs,
the integration keeps the last-known values instead of flapping every entity to
*unavailable*.

Built on the [`liberty-global-gateway`](https://github.com/AboveColin/liberty-global-gateway)
Python library.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/AboveColin/HA-Liberty-Global-Gateway` as an **Integration**.
3. Install **Liberty Global Cable Gateway**, then restart Home Assistant.

### Manual

Copy `custom_components/liberty_global_gateway` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

### Automatic discovery

If **UPnP is enabled** on the gateway, Home Assistant finds it over SSDP and
offers it under **Settings → Devices & services** — you only have to enter the
admin password. The integration confirms the device really is one of these
gateways (via an unauthenticated identification endpoint) before offering it, so
other UPnP routers on the network are ignored.

UPnP is off on some operator builds; in that case, add it manually.

### Manual

**Settings → Devices & services → Add integration → Liberty Global Cable
Gateway.**

- **Gateway address** — pre-filled with a gateway that actually answers on your
  network (`192.168.178.1` on Ziggo, `192.168.0.1` on UPC / Virgin Media).
- **Admin password** — the password printed on the sticker on the gateway,
  unless you changed it.

> Close the gateway's web UI before adding it — the gateway only allows one
> session at a time.

The admin certificate is self-signed, so TLS verification is off by default.

## Notes

- **Local polling**, every 5 minutes. No data leaves your network.
- **Errors after too many wrong passwords:** the gateway locks out login
  attempts for a few minutes after a handful of failures. The setup form reports
  this instead of hammering it.
- **Provisioned speed ≠ measured speed:** the download/upload sensors report the
  DOCSIS service-flow rate caps for your plan, not a live throughput test.

## License

MIT — see [LICENSE](LICENSE).
