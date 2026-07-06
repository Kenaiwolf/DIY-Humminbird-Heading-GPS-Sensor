# DIY Heading and GPS Receiver for Humminbird Sonars

An open-source DIY Heading and GPS Receiver for Humminbird Sonars project documenting the proprietary NMEA 0183
protocol used by Humminbird Helix fish finders to communicate with the AS GPS HS
heading sensor. The goal is to allow any standard GPS + compass module (e.g.
Holybro M9N) to replace the expensive factory sensor.

> **Status:** Protocol fully reverse-engineered and emulation confirmed working on
> Humminbird Helix. Heading displays correctly. GPS position and satellite data
> pass through via UBX. Active development ongoing.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Hardware](#hardware)
3. [Wiring](#wiring)
4. [Protocol Reference](#protocol-reference)
   - [Serial Parameters](#serial-parameters)
   - [Sentence Set](#sentence-set)
   - [Timing](#timing)
   - [$PTSI160 — Heading + Pitch + Roll](#ptsi160--heading--pitch--roll)
   - [Helix Handshake Sequence](#helix-handshake-sequence)
   - [Helix Query-Response](#helix-query-response)
5. [Heading Color: Yellow vs Green](#heading-color-yellow-vs-green)
6. [Tools](#tools)
7. [Log Files](#log-files)
8. [Known Findings & Open Questions](#known-findings--open-questions)
9. [Contributing](#contributing)
10. [Disclaimer](#disclaimer)

---

## How It Works

The Humminbird Helix expects a specific device on its GPS/heading port that speaks
a proprietary dialect of NMEA 0183. The factory device is the **AS GPS HS**
(Humminbird part). This project emulates that device using a PC (or microcontroller)
sitting between the Helix and a standard GPS module.


┌──────────┐  UART 38400  ┌──────────────────┐  UART 38400  ┌──────────┐
│  Helix   │◄────────────►│  Emulator (PC/   │◄────────────►│  M9N GPS │
│  Sonar   │              │  MCU + CH340)    │              │  Module  │
└──────────┘              └──────────────────┘              └──────────┘
                                   │
                              I2C (future)
                                   │
                            ┌──────────────┐
                            │  Compass /   │
                            │  IMU module  │
                            └──────────────┘


The emulator:
1. Forwards GPS data (UBX binary) between the Helix and M9N transparently.
2. Injects the proprietary NMEA sentences the Helix requires to show heading.
3. Responds to heading queries from the Helix in real time.

---

## Hardware

| Component | Notes |
|---|---|
| **Holybro M9N GPS** | u-blox M9N chip, onboard IST8310 compass (I2C), JST-GH 6-pin connector |
| **CH340 USB-to-serial** | Any CH340/CH341 breakout board with 3.3V/5V jumper |
| **PC running Python 3.8+** | Runs the MITM emulator script |
| **Humminbird Helix** | Tested on Helix series; all models compatible with AS GPS HS should behave identically |

> **Note on M9N baud rate:** The M9N ships at 9600 baud on UART1. The Helix
> auto-negotiates the baud rate upward via UBX commands. Set the CH340 script to
> 38400 — the Helix will handle the negotiation. If the M9N was previously
> configured to 115200, reset it to 9600 in u-center before connecting.

---

## Wiring

### CH340 → Holybro M9N (JST-GH 6-pin)

| CH340 Pin | M9N Pin | Signal | Notes |
|---|---|---|---|
| VCC | Pin 1 | 5V power | M9N is 5V powered |
| GND | Pin 6 | Ground | Common ground, mandatory |
| TXD | Pin 2 | UART RX | CH340 transmits → M9N receives |
| RXD | Pin 3 | UART TX | M9N transmits → CH340 receives |
| — | Pin 4 | I2C SCL | Compass — not used yet (future) |
| — | Pin 5 | I2C SDA | Compass — not used yet (future) |

> **Voltage:** M9N UART logic is 3.3V. Set the CH340 jumper to **3.3V** to avoid
> overvoltage on the M9N RX pin. If your CH340 is 5V-only, add a 1kΩ/2kΩ voltage
> divider on the TXD → M9N RX line.

### Helix GPS Port → CH340 (second adapter)

Connect the Helix GPS/heading port to a second CH340 adapter:

| Helix port | CH340 |
|---|---|
| TX | RXD |
| RX | TXD |
| GND | GND |

Both CH340 adapters connect to the same PC running the emulator script.

---

## Protocol Reference

### Serial Parameters

| Parameter | Value |
|---|---|
| Baud rate | **38400** |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |
| Protocol | Pure NMEA 0183 ASCII (no binary framing) |

The single `0x00` byte observed at power-on is a UART line-idle startup glitch,
not a sync byte. There is no baud-rate negotiation on the sensor side.

### Sentence Set

The emulator must send the following sentences to the Helix. All sentences use
standard NMEA 0183 checksum (XOR of all bytes between `$` and `*`, 2-digit
uppercase hex).

| Sentence | Rate | Direction | Purpose |
|---|---|---|---|
| `$GNRMC` | 5 Hz (200ms) | Emulator → Helix | GPS position/time. Void (`V`) when no fix. |
| `$GNGGA` | 5 Hz (200ms) | Emulator → Helix | GPS fix data. Fix quality `0` when no fix. |
| `$GPHDG` | 2 Hz (500ms) | Emulator → Helix | Magnetic heading broadcast. |
| `$PTSI160` | 1 Hz (1000ms) | Emulator → Helix | Proprietary heading + pitch + roll. |

**Without `$GNRMC` and `$GNGGA`, the Helix will not activate heading display.**
These sentences are required even when there is no GPS fix — send them void.

#### Example sentences (no GPS fix)

```
$GNRMC,163223.91,V,,,,,,,,,,N*6C
$GNGGA,163223.91,,,,,0,00,99.99,,,,,,*77
$GPHDG,216.0,0.0,E,0.0,E*5B
$PTSI160,6,-9,216*12
```

#### Example sentences (GPS fix acquired)

```
$GNRMC,163848.40,A,4757.97197,N,01723.51089,E,0.019,,050726,,,A*66
$GNGGA,163848.40,4757.97197,N,01723.51089,E,1,08,1.14,118.6,M,41.1,M,,*42
$GPHDG,257.0,0.0,E,5.5,E*5E
$PTSI160,8,1,257*3C
```

Note: when a GPS fix is present, the magnetic variation field in `$GPHDG` is
populated (e.g. `5.5,E`) instead of `0.0,E`.

### Timing

Timing is measured from the captured AS GPS HS log and must be followed strictly.
The Helix monitors sentence cadence and will reset the sensor connection if
sentences stop or become irregular.

```
t=0ms    → $GNRMC + $GNGGA  (pair, ~10ms apart)
t=150ms  → $GPHDG
t=200ms  → $GNRMC + $GNGGA
t=400ms  → $GNRMC + $GNGGA
t=500ms  → $GPHDG  (+ $PTSI160 on every other GPHDG tick = 1 Hz)
t=600ms  → $GNRMC + $GNGGA
t=800ms  → $GNRMC + $GNGGA
t=1000ms → repeat
```

Use `time.perf_counter()` with accumulating `next_t += interval` (not
`next_t = time.time()`) to prevent timing drift over long sessions.

### $PTSI160 — Heading + Pitch + Roll

```
$PTSI160,V1,V2,HHH*CS
```

| Field | Meaning | Range observed | Notes |
|---|---|---|---|
| `V1` | **Pitch** (integer degrees) | 3 – 8 | Positive = nose up |
| `V2` | **Roll** (integer degrees) | -15 – +1 | Negative = port/left side down |
| `HHH` | Magnetic heading (integer degrees) | 0 – 359 | |
| `CS` | NMEA XOR checksum | — | 2-digit uppercase hex |

**Evidence for pitch/roll interpretation:**
- At startup on a desk with cables pulling the sensor: V1=3–7, V2=0 to -9
  (consistent with a slight nose-up tilt and port-side cable weight).
- After moving the sensor to a window on its twisted wire: V1=8, V2=+1
  (new physical orientation, nearly level roll, more nose-up pitch).
- V1 shows ±1° noise while stationary (normal accelerometer resolution).
- V2 stays rock-solid at -9 while stationary (static cable-induced tilt).

For a static emulator with no IMU, use `V1=6, V2=-9` as a reasonable
approximation of a sensor sitting on a desk. On a real boat mount, both values
will be small (±5°) and relatively stable.

**Checksum calculation:**
```python
def nmea_checksum(sentence_body: str) -> str:
    c = 0
    for ch in sentence_body:
        c ^= ord(ch)
    return f"{c:02X}"

# Example: body = "PTSI160,6,-9,216"
# checksum = nmea_checksum("PTSI160,6,-9,216") → "12"
# full sentence: "$PTSI160,6,-9,216*12\r\n"
```

### Helix Handshake Sequence

The Helix initiates the handshake approximately 38–60 seconds after the emulator
starts sending sentences. The emulator does not need to respond to these — just
keep sending the broadcast sentences and the Helix will proceed automatically.

```
Helix → Emulator:  $PTSI153,5*30    ← identification probe
Helix → Emulator:  $PTSI150,3*35    ← secondary probe
```

After the probes, the Helix enters polling mode and sends queries every ~330ms.

### Helix Query-Response

Once in polling mode, the Helix sends NMEA query sentences to the emulator. The
emulator should respond immediately to heading queries. Other queries (depth,
position, temperature) can be ignored or answered with void/empty responses.

| Helix query | Emulator response | Notes |
|---|---|---|
| `$INHDG,,,V,,V*60` | `$GPHDG,HHH.H,0.0,E,0.0,E*CS` | Respond with current heading |
| `$INHDT,,T*0B` | `$GPHDT,HHH.H,T*CS` | True heading (same value as magnetic for now) |
| `$INDPT,,*47` | *(no response needed)* | Depth query — ignore |
| `$INGLL,,,,,,V*16` | *(no response needed)* | Position query — ignore |
| `$INVTG,,T,,M,,N,,K*5E` | *(no response needed)* | Speed/course query — ignore |
| `$INMTW,,*49` | *(no response needed)* | Water temperature — ignore |
| `$INRMC,,V,...*CS` | *(no response needed)* | RMC query — ignore |
| `$INGGA,,,,,,0,...*CS` | *(no response needed)* | GGA query — ignore |
| `$INZDA,,,,,,*58` | *(no response needed)* | Time query — ignore |

Without broadcast sentences (`$GPHDG`, `$PTSI160`), the Helix polling rate drops
from ~330ms to ~1000ms. The connection stays alive either way.

---

## Heading Color: Yellow vs Green

| Color | Meaning | Condition |
|---|---|---|
| **Yellow** | Heading present, GPS not confirmed | No GPS position fix |
| **Green** | Heading confirmed | GPS fix acquired (fix quality ≥ 1) |

The Helix uses the GPS fix status (received from the M9N via UBX) to determine
whether to show heading as confirmed (green) or unconfirmed (yellow). This is
**not** based on COG vs HDG agreement — on a real boat, wind and current routinely
cause 10–30° difference between COG and HDG, so the Helix cannot use that as a
confirmation criterion.

**To get green heading:** take the unit outdoors so the M9N acquires satellite
lock. The Helix will update its GPS state via UBX and change the heading color
automatically. No changes to the emulator are needed.

**Both `$GPHDG` and `$PTSI160` contribute to the displayed heading.** When they
carry different values (tested experimentally), some Helix models oscillate between
the two values and others display an average. Always keep them in sync.

---

## Tools

### `MITM_Sniff2.py` — Protocol Sniffer

A Man-in-the-Middle serial proxy that sits between the Helix and the real AS GPS HS
(or any device). Forwards all bytes in both directions and logs everything.

**Usage:**
```
pip install pyserial
python MITM_Sniff2.py
```

Configure `HELIX_PORT`, `AS_GPS_HS_PORT`, and `BAUD_RATE` at the top of the file.

**Output files (per session):**

| File | Contents |
|---|---|
| `serial_log_TIMESTAMP.bin` | Raw bytes from both directions, interleaved |
| `timestamp_log_TIMESTAMP.csv` | Every raw chunk with timestamp, direction, hex |
| `nmea_log_TIMESTAMP.txt` | Decoded NMEA sentences with timestamps |

### `MITM_emul.py` — Heading Emulator / Diagnostic Tool

Replaces the AS GPS HS. Forwards GPS (UBX) between Helix and M9N, and injects
the required heading sentences. Includes:

- Separate independent timers for `$GNRMC`/`$GNGGA` (5 Hz), `$GPHDG` (2 Hz),
  and `$PTSI160` (1 Hz).
- Responds to `$INHDG` and `$INHDT` queries from the Helix in real time.
- `ValueGenerator` with multiple diagnostic sweep modes for V1/V2/heading testing.
- Keyboard-controlled mode switching at runtime (Windows: `msvcrt`).
- Full logging identical to `MITM_Sniff2.py`.

**Keyboard controls:**

| Key | Action |
|---|---|
| `M` | Cycle to next test mode |
| `N` | Advance to next value in current sweep |
| `P` | Previous value |
| `R` | Reset sweep to start |
| `+` / `-` | Increase / decrease dwell time per step |
| `H` | Toggle `$GPHDG` on/off |
| `T` | Toggle `$PTSI160` on/off |
| `Q` / Ctrl+C | Stop |

**Test modes:**

| Mode | What cycles | Fixed values |
|---|---|---|
| `static` | Nothing | V1=6, V2=-9, HHH=216 |
| `v1_sweep` | V1: 0 → 15 | V2=-9, HHH=216 |
| `v2_sweep` | V2: -15 → +15 | V1=6, HHH=216 |
| `v1v2_grid` | All (V1, V2) pairs | HHH=216 |
| `heading_sweep` | HHH: 0 → 350 step 10 | V1=6, V2=-9 |

---

## Log Files

All captured session logs are in the repository root.

| File | Session | Description |
|---|---|---|
| `nmea_log_20260705_183137.txt` | Original AS GPS HS | Real sensor capture, includes GPS fix outdoors |
| `serial_log_20260705_183137.bin` | Original AS GPS HS | Raw binary of the same session |
| `timestamp_log_20260705_183137.csv` | Original AS GPS HS | Full hex log of every byte |
| `nmea_log_20260706_010331.txt` | Emulator V1/V2 sweep | V1 sweep (0–15), V2 sweep (-15 to +15), V1V2 grid |
| `nmea_log_20260706_013844.txt` | Split-heading test | GPHDG vs PTSI160 isolation test, 7 phases |
| `serial_log_20260706_013844.bin` | Split-heading test | Raw binary including UBX M9N traffic |

---

## Known Findings & Open Questions

### Confirmed

- **`$GNRMC` + `$GNGGA` are mandatory.** Without them the Helix does not activate
  heading display. The real AS GPS HS sends them at 5 Hz even with no GPS fix.
- **`$PTSI160` V1 = pitch, V2 = roll** (integer degrees). Confirmed by correlating
  values with physical sensor movement and repositioning.
- **Both `$GPHDG` and `$PTSI160` drive the heading display.** They must be kept
  in sync.
- **Query-response alone is sufficient** to maintain the Helix connection (tested
  in RESP_ONLY mode), but broadcast sentences are needed for the 330ms polling rate.
- **The Helix communicates with the M9N via UBX binary protocol**, not NMEA. The
  Helix auto-negotiates baud rate from 9600 upward via UBX-CFG-PRT commands.
- **Yellow heading = no GPS fix.** Green heading requires satellite lock. This is
  not related to COG vs HDG agreement.
- **No binary protocol on the sensor side.** The AS GPS HS → Helix link is pure
  NMEA 0183 ASCII at 38400 baud. The single `0x00` at power-on is a UART glitch.

### Open Questions

- **Exact sign convention for V1/V2.** Positive V1 = nose up is confirmed.
  For V2: negative = port down is the working hypothesis based on one session.
  Needs confirmation with a known-orientation mount.
- **Whether the Helix uses V1/V2 for tilt compensation** of the displayed heading,
  or only for diagnostics/display. The heading value in `$PTSI160` is always an
  integer — if tilt compensation were applied internally, sub-degree precision
  would be expected.
- **`$PTSI153` response.** The Helix sends `$PTSI153,5*30` as a probe. The real
  AS GPS HS may send a response not captured in the MITM log. So far the emulator
  works without responding to it.
- **I2C compass integration.** The M9N's IST8310 compass is connected via I2C but
  not yet read by the emulator. Currently using static heading. Next step: read
  pitch and roll from the accelerometer and feed into V1/V2.

---

## Contributing

Contributions are welcome. The most valuable contributions are:

- **Logs from other Helix models** — upload to the repository root following the
  naming convention `nmea_log_YYYYMMDD_HHMMSS.txt` etc.
- **I2C compass integration** — reading IST8310 or any other compass/IMU and
  feeding real heading, pitch, and roll into the emulator.
- **Microcontroller port** — porting the emulator logic to ESP32 or Arduino for
  a standalone device without a PC.
- **Magnetic variation** — integrating a WMM (World Magnetic Model) library to
  populate the variation field in `$GPHDG` correctly from GPS position.

Please include comments in all code and follow the existing log format so sessions
remain comparable.

---

## Disclaimer

This project is an independent DIY initiative. It is not affiliated with,
endorsed by, or sponsored by Humminbird or its parent company Johnson Outdoors.
Use at your own risk. Do not rely on this for safety-critical navigation.


