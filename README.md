# Ziggo Cable Gateway (Sagemcom / Compal F3896LG) — Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for the **F3896LG** DOCSIS 3.1 cable gateway that
**Ziggo** (and other Liberty Global operators) ship in the Netherlands. It reads
the gateway's local admin REST API — no cloud, all polling stays on your LAN.

> **Known by many names.** This is the modem/router Ziggo hands out as the
> *"Ziggo SmartWifi"* box. Depending on the batch it is branded **Sagemcom
> F@st 3896 / F3896LG** or **Compal F3896LG** — they share the same firmware and
> API, so this integration works with all of them. If you searched for *Ziggo
> modem*, *Sagemcom F3896*, *Compal F3896LG*, *Ziggo SmartWifi*, or *Liberty
> Global F3896LG* — this is the one.

_Unofficial and not affiliated with, endorsed by, or connected to Sagemcom,
Compal, Liberty Global, Ziggo or VodafoneZiggo. Use on your own gateway at your
own risk._

## What you get

A single **Ziggo Cable Gateway** device with:

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
- Firmware version
- Gateway LAN IP and IPv6 delegated prefix
- Wi-Fi 2.4 GHz / 5 GHz SSID (with channel, width and security as attributes)
- **Last event** — the newest cable-modem event-log line, with its timestamp,
  priority and total event count as attributes

**Binary sensors**
- Modem operational (connectivity)
- Registration complete and Downstream locked
- Baseline privacy (BPI+)
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

**Button**
- Reboot gateway (drops the WAN for a minute or two — a deliberate action).

## How it handles the single-session gateway

The F3896LG allows **exactly one authenticated session**. This integration logs
in, reads everything in one burst, and then **logs out** (`DELETE
/user/<id>/token/<token>`) every polling cycle (every 5 minutes), so the
gateway's single session is freed immediately and its web UI stays usable
between polls. Successful logins never count toward the lockout, so the regular
cadence is safe. If the web UI is open (holding the session) when a poll runs,
the integration keeps the last-known values instead of flapping every entity to
*unavailable*.

Built on the [`compalf3896lg`](https://github.com/AboveColin/compalf3896lg)
Python library.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/AboveColin/HA-Compal-F3896LG` as an **Integration**.
3. Install **Ziggo Cable Gateway (F3896LG)**, then restart Home Assistant.

### Manual

Copy `custom_components/compal_f3896lg` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & services → Add integration → Ziggo Cable Gateway.**

- **Gateway address** — usually `192.168.178.1`.
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
