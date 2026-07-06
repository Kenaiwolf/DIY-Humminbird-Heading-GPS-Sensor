# DIY Heading and GPS Receiver for Humminbird Sonars

This project provides an open-source solution for interfacing custom GPS and
heading sensors with Humminbird sonar units (specifically the Helix series).
The goal is to provide a modern, affordable, and DIY-friendly alternative to
the factory AS GPS HS sensor by emulating the proprietary NMEA 0183 protocol
required by Humminbird devices.

## Support the Project

If this project helped you save money or improved your boat's navigation,
please consider supporting the ongoing development. Your contributions help
cover hardware costs and the time spent refining the protocol.
Any help welcomed, just send me an email. 
---

## Overview

The Humminbird Helix series communicates with its GPS/heading sensor over a
single RS-232 serial link at **38400 baud, 8N1**. The protocol is pure
**NMEA 0183 ASCII** — there is no binary framing, no proprietary baud-rate
negotiation, and no special startup sequence required from the sensor side.

The sensor must send four sentence types at specific rates. Missing
`$GNRMC`/`$GNGGA` causes the Helix to repeatedly reset its GPS satellite
search. Missing `$PTSI160` causes the heading to not appear on screen.

---

## Protocol — Sentence Set (Sensor → Helix)

All sentences use standard NMEA 0183 checksum (`*XX\r\n` terminator).

### Timing (strictly observed in captured logs)

| Sentence | Rate | Interval | Notes |
|---|---|---|---|
| `$GNRMC` | 5 Hz | 200 ms | **Mandatory.** Void (`V`) when no GPS fix. |
| `$GNGGA` | 5 Hz | 200 ms | **Mandatory.** Fix quality `0` when no fix. |
| `$GPHDG` | 2 Hz | 500 ms | Magnetic heading. |
| `$PTSI160` | 1 Hz | 1000 ms | Proprietary heading + tilt. Always immediately after a `$GPHDG` tick. |

`$GNRMC` and `$GNGGA` are sent as a pair (GGA follows RMC by ~10 ms).
`$GPHDG` appears ~150 ms after a `$GNRMC`/`$GNGGA` pair.
`$PTSI160` fires on every second `$GPHDG` tick (i.e., every 1000 ms).

### Sentence formats

**No GPS fix (typical at startup or indoors):**
```
$GNRMC,HHMMSS.ss,V,,,,,,,,,,N*CS
$GNGGA,HHMMSS.ss,,,,,0,00,99.99,,,,,,*CS
$GPHDG,HHH.H,0.0,E,0.0,E*CS
$PTSI160,V1,V2,HHH*CS
```

**GPS fix acquired:**
```
$GNRMC,HHMMSS.ss,A,DDMM.mmmmm,N,DDDMM.mmmmm,E,SPD,,DDMMYY,,,A*CS
$GNGGA,HHMMSS.ss,DDMM.mmmmm,N,DDDMM.mmmmm,E,1,NN,H.HH,ALT,M,GEO,M,,*CS
$GPHDG,HHH.H,0.0,E,MAG_VAR,E*CS
$PTSI160,V1,V2,HHH*CS
```

### $PTSI160 — Field Definitions

```
$PTSI160,V1,V2,HHH*CS
```

| Field | Meaning | Unit | Notes |
|---|---|---|---|
| `V1` | **Pitch** | Integer degrees | Positive = nose up. Range observed: 3–8. |
| `V2` | **Roll** | Integer degrees | Negative = port side down, positive = starboard side down. Range observed: -15 to +1. |
| `HHH` | **Magnetic heading** | Integer degrees | 0–359. Must match `$GPHDG`. |

**Evidence:** In the original AS GPS HS capture, the sensor was stationary on
a desk with cables pulling it to one side: V1 oscillated 5–6°, V2 held steady
at -9° (permanent cable-induced tilt). When the sensor was moved to a window
for GPS lock and placed on its twisted cable, both values changed simultaneously
to V1=8, V2=+1, consistent with a new physical orientation.

### $GPHDG — Magnetic Variation

When no GPS fix: variation field is `0.0,E` (zero).
When GPS fix acquired: variation field is populated from the GPS almanac
(e.g., `5.5,E` for Eastern Europe).

---

## Helix Initialization Sequence

After power-on, the Helix waits approximately 59 seconds before sending its
first probe sentence. The full handshake:

1. **~59 s after first sentence received:**
   Helix → Sensor: `$PTSI153,5*30`

2. **~14 s later:**
   Helix → Sensor: `$PTSI150,3*35`

3. **Immediately after `$PTSI150`:** Helix begins normal NMEA output on the
   same port (see section below).

The sensor does **not** need to reply to either probe sentence. The Helix
proceeds regardless. No re-probe occurs as long as the sensor keeps sending
its sentence set.

---

## Helix NMEA Output ($IN Sentences)

The Helix outputs its own NMEA sentences on the same serial port it uses to
communicate with the sensor. The talker ID `IN` is Humminbird's proprietary
identifier (Integrated Navigation). These sentences can be turned on/off in
the Helix settings and can also be switched to standard `$GN` prefix.

The emulator does **not** need to parse or respond to these sentences.
They are informational output only.

| Sentence | Content | Rate |
|---|---|---|
| `$INHDG,,,V,,V*60` | Heading (void when no GPS fix) | ~1 Hz |
| `$INHDT,,T*0B` | True heading (void) | ~1 Hz |
| `$INDPT,,*47` | Depth (void) | ~1 Hz |
| `$INRMC,,V,...` | RMC position (void) | ~1 Hz |
| `$INGLL,,,,,,V*16` | GLL position (void) | ~0.5 Hz |
| `$INVTG,,T,,M,,N,,K*5E` | Speed/course (void) | ~0.5 Hz |
| `$INGGA,,,,,,0,...` | GGA position (void) | ~0.5 Hz |
| `$INZDA,,,,,,*58` | Date/time (void) | ~0.5 Hz |
| `$INMTW,,*49` | Water temperature (void) | ~0.5 Hz |

---

## Heading Color on Screen — Yellow vs Green

**Yellow heading is normal and expected.** Even the original AS GPS HS shows
yellow heading. This is Humminbird's color coding:

- **Yellow** = HDG — compass-derived magnetic heading from the sensor
- **Green** = COG — GPS-derived course over ground

These are fundamentally different data sources. On a real boat, HDG and COG
almost never agree due to wind and current (leeway/set and drift), so the
Helix always displays them separately with different colors. Yellow heading
does not indicate an error or missing data.

---

## Hardware

### Minimum Required Components

| Component | Purpose |
|---|---|
| Microcontroller (ESP32, Arduino, Raspberry Pi, etc.) | Runs the emulator firmware |
| Magnetometer / compass module | Provides magnetic heading |
| CH340 or similar USB-UART adapter | PC-based testing / MITM logging |
| GPS module (e.g., Holybro M9N, u-blox NEO-M9N) | GPS position + time |

### CH340 → Holybro M9N Wiring (UART)

The Holybro M9N uses a JST-GH 6-pin connector:

| M9N Pin | Signal | CH340 Pin | Notes |
|---|---|---|---|
| 1 | VCC (5 V) | VCC | Power from CH340 board |
| 2 | UART RX | TXD | CH340 transmits → M9N receives |
| 3 | UART TX | RXD | M9N transmits → CH340 receives |
| 4 | I2C SCL | — | Compass only, not used for UART |
| 5 | I2C SDA | — | Compass only, not used for UART |
| 6 | GND | GND | Common ground, mandatory |

> **Voltage warning:** The M9N UART logic is 3.3 V. Set the CH340 board
> jumper to **3.3 V**. If your CH340 is 5 V only, add a voltage divider
> (1 kΩ + 2 kΩ) on the TXD → M9N RX line to avoid damaging the module.

**Default baud rate:** The M9N ships at 38400 baud on UART1, matching the
Helix. If the M9N has been reconfigured (e.g., to 115200), use u-center to
reset it to 38400 before connecting.

### Helix Serial Port

Connect the sensor to the Helix's GPS/heading port (the dedicated 4-pin
Humminbird accessory connector). Baud rate: **38400, 8N1**.

---

## NMEA Checksum Calculation

```python
def nmea_checksum(sentence: str) -> str:
    """
    Input:  sentence body without $ prefix and without *CS suffix
    Output: two-character uppercase hex checksum string
    Example: nmea_checksum("GPHDG,216.0,0.0,E,0.0,E") -> "5B"
    """
    c = 0
    for ch in sentence:
        c ^= ord(ch)
    return f"{c:02X}"

def build_sentence(body: str) -> bytes:
    cs = nmea_checksum(body)
    return f"${body}*{cs}\r\n".encode("ascii")
```

---

## Tools

### MITM_Sniff2.py — Protocol Capture Tool

Sits between the Helix and the real AS GPS HS (or any sensor) and logs all
traffic in both directions without modifying it.

**Configuration:**
```python
HELIX_PORT    = "COM1"   # port connected to Helix
AS_GPS_HS_PORT = "COM10" # port connected to sensor
BAUD_RATE     = 38400
```

**Output files per session:**

| File | Contents |
|---|---|
| `serial_log_YYYYMMDD_HHMMSS.bin` | Raw binary — every byte from both directions |
| `timestamp_log_YYYYMMDD_HHMMSS.csv` | Timestamped hex dump of every read chunk |
| `nmea_log_YYYYMMDD_HHMMSS.txt` | Human-readable NMEA sentences with timestamps |

### MITM_emul.py / MITM_emul2.py — Emulator / Diagnostic Tool

Replaces the real AS GPS HS. Injects heading sentences into the Helix stream
while forwarding GPS data from a real GPS module (e.g., M9N).

**Key features:**
- Separate independent timers for `$GNRMC`/`$GNGGA` (200 ms), `$GPHDG`
  (500 ms), and `$PTSI160` (1000 ms) — strictly matching real sensor timing
- Multiple `$PTSI160` test modes: `static`, `v1_sweep`, `v2_sweep`,
  `v1v2_grid`, `heading_sweep`
- Runtime mode switching via keyboard (Windows `msvcrt`)
- Configurable dwell time per test step
- Full MITM logging (same format as MITM_Sniff2.py)
- Thread-safe write lock on the Helix port

**Keyboard controls (runtime):**
| Key | Action |
|---|---|
| `M` | Cycle to next test mode |
| `N` | Advance to next value (skip dwell) |
| `P` | Previous value |
| `R` | Reset to start of current mode |
| `+` / `-` | Increase / decrease dwell time by 5 s |
| `H` | Toggle `$GPHDG` on/off |
| `T` | Toggle `$PTSI160` on/off |
| `Q` / Ctrl+C | Stop |

---

## Captured Log Files

| Session | File | Description |
|---|---|---|
| 2026-07-05 18:31 | `nmea_log_20260705_183137.txt` | **Original AS GPS HS** — real sensor, no fix → GPS fix acquired outdoors. Reference capture. |
| 2026-07-05 18:31 | `serial_log_20260705_183137.bin` | Raw binary of above session |
| 2026-07-05 23:47 | `nmea_log_20260705_234714.txt` | First emulator test — heading injection working, M9N on wrong baud |
| 2026-07-05 23:47 | `serial_log_20260705_234714.bin` | Raw binary of above session |
| 2026-07-06 01:03 | `nmea_log_20260706_010331.txt` | V1/V2 sweep test — confirmed V1 and V2 do not affect displayed heading |
| 2026-07-06 01:38 | `nmea_log_20260706_013844.txt` | Split-heading test — confirmed both `$GPHDG` and `$PTSI160` contribute to display |

---

## Key Findings Summary

1. **Protocol is pure NMEA ASCII.** No binary framing, no baud negotiation.
   38400 baud, 8N1.

2. **`$GNRMC` and `$GNGGA` are mandatory.** Without them the Helix resets
   its GPS satellite search repeatedly. Send them void (no fix) at 5 Hz from
   the moment the sensor powers on.

3. **`$PTSI160` V1 = pitch, V2 = roll** (integer degrees). The Helix uses
   these for tilt display. They do not affect the heading value shown on
   screen. For a fixed mount, use measured static tilt values. For a dynamic
   mount, read from an IMU.

4. **Both `$GPHDG` and `$PTSI160` contribute to the displayed heading.**
   When they conflict, the Helix averages or oscillates between them. Keep
   both sentences in sync with the same heading value.

5. **The Helix does not require a response to its probe sentences**
   (`$PTSI153`, `$PTSI150`). It proceeds to normal operation regardless.

6. **Yellow heading is normal.** Yellow = compass HDG, Green = GPS COG.
   This is Humminbird's standard color coding, not an error indicator.

7. **The Helix outputs its own NMEA sentences** (`$INHDG`, `$INRMC`, etc.)
   on the same port. These are normal output sentences (talker ID `IN` =
   Humminbird). They can be turned off or switched to `$GN` in Helix settings.
   The sensor does not need to respond to them.

8. **Helix initialization takes ~59 seconds** from first sentence received
   before it sends `$PTSI153`. This is normal.

---

## Getting Started

1. **Capture your own logs** using `MITM_Sniff2.py` to verify your specific
   Helix model behaves the same way.

2. **Run the emulator** (`MITM_emul2.py`) with a CH340 on COM1 (Helix side)
   and your GPS module on COM10. Start in `static` mode to confirm heading
   appears on screen.

3. **Connect your compass** (e.g., IST8310 via I2C on the M9N) and feed
   real pitch/roll into V1/V2 and real heading into `$GPHDG` and `$PTSI160`.

4. **Take it outdoors** to acquire a GPS fix. The `$GNRMC`/`$GNGGA` sentences
   will automatically populate with real position data once the GPS module
   has a fix.

---

## Contributing

This is a community-driven project. Contributions welcome:

- **Add logs:** If you have logs from different Humminbird devices, please
  upload them to the `/data` folder.
- **Test other Helix models:** The protocol is expected to be identical across
  all Helix models compatible with the AS GPS HS accessory.
- **Improve the emulator:** Pull requests welcome. Please include comments in
  all code and follow the existing log format so sessions remain comparable.

---

## Disclaimer

This project is an independent DIY initiative. It is not affiliated with,
endorsed by, or sponsored by Humminbird or its parent company Johnson Outdoors.
Use at your own risk. Do not rely on this for safety-critical navigation.
``` [1](#31-0) [2](#31-1) [3](#31-2) [4](#31-3) [5](#31-4)

### Citations

**File:** nmea_log_20260705_183137.txt (L1-4)
```text
[2026-07-05 18:31:49.720] [AS_GPS_HS->Helix] $GNRMC,,V,,,,,,,,,,N*4D
[2026-07-05 18:31:49.730] [AS_GPS_HS->Helix] $GNGGA,,,,,,0,00,99.99,,,,,,*56
[2026-07-05 18:31:49.870] [AS_GPS_HS->Helix] $GPHDG,216.0,0.0,E,0.0,E*5B
[2026-07-05 18:31:49.870] [AS_GPS_HS->Helix] $PTSI160,3,0,216*33
```

**File:** nmea_log_20260705_183137.txt (L5850-5868)
```text
[2026-07-05 18:38:47.487] [AS_GPS_HS->Helix] $GNRMC,163848.40,A,4757.97197,N,01723.51089,E,0.019,,050726,,,A*66
[2026-07-05 18:38:47.507] [AS_GPS_HS->Helix] $GNGGA,163848.40,4757.97197,N,01723.51089,E,1,08,1.14,118.6,M,41.1,M,,*42
[2026-07-05 18:38:47.687] [AS_GPS_HS->Helix] $GNRMC,163848.60,A,4757.97196,N,01723.51089,E,0.052,,050726,,,A*6A
[2026-07-05 18:38:47.707] [AS_GPS_HS->Helix] $GNGGA,163848.60,4757.97196,N,01723.51089,E,1,08,1.14,118.7,M,41.1,M,,*40
[2026-07-05 18:38:47.857] [AS_GPS_HS->Helix] $GPHDG,257.0,0.0,E,5.5,E*5E
[2026-07-05 18:38:47.867] [AS_GPS_HS->Helix] $PTSI160,8,1,257*3C
[2026-07-05 18:38:47.887] [AS_GPS_HS->Helix] $GNRMC,163848.80,A,4757.97196,N,01723.51087,E,0.144,,050726,,,A*6C
[2026-07-05 18:38:47.907] [AS_GPS_HS->Helix] $GNGGA,163848.80,4757.97196,N,01723.51087,E,1,08,1.14,118.7,M,41.1,M,,*40
[2026-07-05 18:38:48.087] [AS_GPS_HS->Helix] $GNRMC,163849.00,A,4757.97196,N,01723.51087,E,0.092,,050726,,,A*6F
[2026-07-05 18:38:48.107] [AS_GPS_HS->Helix] $GNGGA,163849.00,4757.97196,N,01723.51087,E,1,07,1.17,118.7,M,41.1,M,,*45
[2026-07-05 18:38:48.287] [AS_GPS_HS->Helix] $GNRMC,163849.20,A,4757.97195,N,01723.51087,E,0.106,,050726,,,A*62
[2026-07-05 18:38:48.307] [AS_GPS_HS->Helix] $GNGGA,163849.20,4757.97195,N,01723.51087,E,1,07,1.17,118.7,M,41.1,M,,*44
[2026-07-05 18:38:48.357] [AS_GPS_HS->Helix] $GPHDG,258.0,0.0,E,5.5,E*51
[2026-07-05 18:38:48.488] [AS_GPS_HS->Helix] $GNRMC,163849.40,A,4757.97195,N,01723.51083,E,0.236,,050726,,,A*60
[2026-07-05 18:38:48.508] [AS_GPS_HS->Helix] $GNGGA,163849.40,4757.97195,N,01723.51083,E,1,07,1.17,118.9,M,41.1,M,,*48
[2026-07-05 18:38:48.688] [AS_GPS_HS->Helix] $GNRMC,163849.60,A,4757.97195,N,01723.51084,E,0.020,,050726,,,A*60
[2026-07-05 18:38:48.708] [AS_GPS_HS->Helix] $GNGGA,163849.60,4757.97195,N,01723.51084,E,1,08,1.14,118.9,M,41.1,M,,*41
[2026-07-05 18:38:48.858] [AS_GPS_HS->Helix] $GPHDG,257.0,0.0,E,5.5,E*5E
[2026-07-05 18:38:48.868] [AS_GPS_HS->Helix] $PTSI160,8,1,257*3C
```

**File:** nmea_log_20260706_013844.txt (L1749-1770)
```text
[2026-07-06 01:42:14.304] [PhaseAuto] NOTE: Phase 7/7: RESP_ONLY  GPHDG=OFF PTSI=OFF RESP=90
[2026-07-06 01:42:14.790] [Helix->M9N] $INDPT,,*47
[2026-07-06 01:42:14.794] [Helix->M9N] $INHDG,,,V,,V*60
[2026-07-06 01:42:14.794] [RESP->Helix] $GPHDG,90.0,0.0,E,0.0,E*67
[2026-07-06 01:42:14.800] [Helix->M9N] $INHDT,,T*0B
[2026-07-06 01:42:14.800] [RESP->Helix] $GPHDT,90.0,T*0C
[2026-07-06 01:42:14.807] [Helix->M9N] $INRMC,,V,,,,,,,,,*21
[2026-07-06 01:42:15.790] [Helix->M9N] $INDPT,,*47
[2026-07-06 01:42:15.794] [Helix->M9N] $INHDG,,,V,,V*60
[2026-07-06 01:42:15.794] [RESP->Helix] $GPHDG,90.0,0.0,E,0.0,E*67
[2026-07-06 01:42:15.798] [Helix->M9N] $INHDT,,T*0B
[2026-07-06 01:42:15.798] [RESP->Helix] $GPHDT,90.0,T*0C
[2026-07-06 01:42:15.806] [Helix->M9N] $INGLL,,,,,,V*16
[2026-07-06 01:42:15.810] [Helix->M9N] $INVTG,,T,,M,,N,,K*5E
[2026-07-06 01:42:15.816] [Helix->M9N] $INMTW,,*49
[2026-07-06 01:42:16.789] [Helix->M9N] $INDPT,,*47
[2026-07-06 01:42:16.794] [Helix->M9N] $INHDG,,,V,,V*60
[2026-07-06 01:42:16.794] [RESP->Helix] $GPHDG,90.0,0.0,E,0.0,E*67
[2026-07-06 01:42:16.802] [Helix->M9N] $INHDT,,T*0B
[2026-07-06 01:42:16.803] [RESP->Helix] $GPHDT,90.0,T*0C
[2026-07-06 01:42:16.810] [Helix->M9N] $INRMC,,V,,,,,,,,,*21
[2026-07-06 01:42:17.789] [Helix->M9N] $INDPT,,*47
```

**File:** MITM_Sniff2.py (L29-31)
```python
HELIX_PORT = "COM1"
AS_GPS_HS_PORT = "COM10"
BAUD_RATE = 38400
```

**File:** MITM_Sniff2.py (L40-42)
```python
LOG_FILE_BIN = os.path.join(SCRIPT_DIR, f"serial_log_{SESSION_TS}.bin")
LOG_FILE_CSV = os.path.join(SCRIPT_DIR, f"timestamp_log_{SESSION_TS}.csv")
LOG_FILE_TXT = os.path.join(SCRIPT_DIR, f"nmea_log_{SESSION_TS}.txt")
```
