#!/usr/bin/env python3
"""
MITM serial proxy between HELIX_PORT and AS_GPS_HS_PORT.

Features:
- Bidirectional forwarding between COM1 (Helix) and COM10 (AS GPS HS).
- Logs raw bytes with timestamps.
- Extracts and logs full NMEA sentences from both directions.
- Graceful shutdown and buffered parsing to reduce dropped logs.

Requirements: pyserial
"""

import time
import threading
import csv
import datetime
import queue
import os
import signal
import binascii

try:
    import serial
except Exception:
    serial = None

# ----- Configuration -----
HELIX_PORT = "COM1"
AS_GPS_HS_PORT = "COM10"
BAUD_RATE = 38400

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

SESSION_TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

LOG_FILE_BIN = os.path.join(SCRIPT_DIR, f"serial_log_{SESSION_TS}.bin")
LOG_FILE_CSV = os.path.join(SCRIPT_DIR, f"timestamp_log_{SESSION_TS}.csv")
LOG_FILE_TXT = os.path.join(SCRIPT_DIR, f"nmea_log_{SESSION_TS}.txt")

log_queue = queue.Queue(maxsize=20000)
stop_event = threading.Event()
THREAD_EXCEPTION_QUEUE = queue.Queue()
LOGGER_SENTINEL = object()


# ----- Utilities -----
def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def calculate_checksum_bytes(payload: bytes) -> str:
    c = 0
    for b in payload:
        c ^= b
    return f"{c:02X}"


def is_valid_nmea(line: bytes) -> bool:
    try:
        if not line.startswith(b"$"):
            return False
        if b"*" not in line:
            return False

        star_idx = line.rfind(b"*")
        if star_idx < 2:
            return False
        if len(line) < star_idx + 3:
            return False

        body = line[1:star_idx]
        expected = calculate_checksum_bytes(body)
        actual = line[star_idx + 1:star_idx + 3].decode("ascii", errors="ignore").upper()
        return expected == actual
    except Exception:
        return False


def put_log(item):
    try:
        log_queue.put(item, timeout=1.0)
    except queue.Full:
        try:
            log_queue.get_nowait()
        except Exception:
            pass
        try:
            log_queue.put_nowait(item)
        except Exception:
            pass


def hexlify(data: bytes) -> str:
    return binascii.hexlify(data).decode("ascii").upper()


def parse_nmea_lines_from_buffer(buf: bytearray):
    sentences = []
    while True:
        lf = buf.find(b"\n")
        if lf == -1:
            break
        line = bytes(buf[:lf + 1])
        del buf[:lf + 1]
        sentences.append(line)
    return sentences


# ----- Logger thread -----
def async_logger_worker():
    try:
        with open(LOG_FILE_BIN, "ab") as f_bin, \
             open(LOG_FILE_TXT, "a", encoding="utf-8", errors="replace", buffering=1) as f_txt, \
             open(LOG_FILE_CSV, "a", newline="", encoding="utf-8", errors="replace", buffering=1) as f_csv:

            csv_writer = csv.writer(f_csv)
            if f_csv.tell() == 0:
                csv_writer.writerow(["timestamp", "direction", "type", "message"])

            while True:
                try:
                    item = log_queue.get(timeout=0.5)
                except queue.Empty:
                    if stop_event.is_set():
                        break
                    continue

                if item is LOGGER_SENTINEL:
                    break

                try:
                    log_type, direction, data = item
                except Exception:
                    continue

                ts = now_ts()

                try:
                    if log_type == "raw":
                        f_bin.write(data)
                        f_bin.flush()
                        csv_writer.writerow([ts, direction, "raw", f"RAW_LEN={len(data)} HEX={hexlify(data)}"])

                    elif log_type == "nmea":
                        decoded = data.decode("ascii", errors="replace").rstrip("\r\n")
                        f_txt.write(f"[{ts}] [{direction}] {decoded}\n")
                        csv_writer.writerow([ts, direction, "nmea", decoded])

                    elif log_type == "note":
                        msg = str(data)
                        f_txt.write(f"[{ts}] [{direction}] {msg}\n")
                        csv_writer.writerow([ts, direction, "note", msg])

                    else:
                        msg = hexlify(data) if isinstance(data, (bytes, bytearray)) else str(data)
                        f_txt.write(f"[{ts}] [{direction}] {msg}\n")
                        csv_writer.writerow([ts, direction, "other", msg])

                    f_csv.flush()
                    f_txt.flush()
                except Exception:
                    pass

    except Exception as e:
        THREAD_EXCEPTION_QUEUE.put(e)
        stop_event.set()


# ----- Buffered reader that extracts full NMEA sentences -----
class SerialBufferReader:
    def __init__(self, ser):
        self.ser = ser
        self.buf = bytearray()

    def read_available(self, size_hint=4096):
        try:
            n = self.ser.in_waiting
            if n and n > 0:
                return self.ser.read(min(n, size_hint))
            return self.ser.read(1)
        except Exception:
            return b""

    def feed(self, data: bytes):
        if not data:
            return []
        self.buf.extend(data)
        return parse_nmea_lines_from_buffer(self.buf)

    def flush(self):
        if not self.buf:
            return b""
        rem = bytes(self.buf)
        self.buf.clear()
        return rem


def log_sentences_from_chunk(direction: str, chunk: bytes):
    """
    Log any complete NMEA lines inside a chunk.
    Also logs invalid/partial lines that start with '$'.
    """
    temp = bytearray(chunk)
    lines = parse_nmea_lines_from_buffer(temp)
    for s in lines:
        if is_valid_nmea(s):
            put_log(("nmea", direction, s))
        elif s.startswith(b"$"):
            put_log(("note", direction, f"partial/invalid NMEA: {s!r}"))


# ----- Forwarding threads -----
def forwarder(ser_src, ser_dst, name_src, name_dst):
    reader = SerialBufferReader(ser_src)

    try:
        while not stop_event.is_set():
            data = reader.read_available()

            if not data:
                continue

            direction = f"{name_src}->{name_dst}"

            # Parse/log NMEA first so a write failure doesn't lose the record
            try:
                reader.buf.extend(data)
                sentences = parse_nmea_lines_from_buffer(reader.buf)
                for s in sentences:
                    if is_valid_nmea(s):
                        put_log(("nmea", direction, s))
                    elif s.startswith(b"$"):
                        put_log(("note", direction, f"partial/invalid NMEA: {s!r}"))
            except Exception:
                pass

            put_log(("raw", direction, data))

            try:
                ser_dst.write(data)
            except Exception as e:
                put_log(("note", direction, f"write failed: {e}"))
                stop_event.set()
                break

    except Exception as e:
        THREAD_EXCEPTION_QUEUE.put(e)
        stop_event.set()

    # Flush leftover partial data
    leftover = reader.flush()
    if leftover:
        direction = f"{name_src}->{name_dst}-flush"
        put_log(("raw", direction, leftover))
        if leftover.startswith(b"$"):
            put_log(("note", direction, f"leftover partial NMEA: {leftover!r}"))


# ----- Main -----
def main():
    if serial is None:
        print("pyserial not installed; install with: pip install pyserial")
        return

    print("Log files will be written here:")
    print(" BIN:", LOG_FILE_BIN)
    print(" CSV:", LOG_FILE_CSV)
    print(" TXT:", LOG_FILE_TXT)

    def _signal_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        pass

    logger_thread = threading.Thread(target=async_logger_worker, daemon=False, name="LoggerThread")
    logger_thread.start()

    ser_helix = None
    ser_as_gps_hs = None
    t_h_a = None
    t_a_h = None

    try:
        ser_helix = serial.Serial(
            HELIX_PORT,
            BAUD_RATE,
            timeout=0.05,
            write_timeout=1.0,
        )
        ser_as_gps_hs = serial.Serial(
            AS_GPS_HS_PORT,
            BAUD_RATE,
            timeout=0.05,
            write_timeout=1.0,
        )
    except Exception as e:
        print("Port Error:", e)
        stop_event.set()
        put_log(LOGGER_SENTINEL)
        logger_thread.join(timeout=5)
        return

    t_h_a = threading.Thread(
        target=forwarder,
        args=(ser_helix, ser_as_gps_hs, "Helix", "AS_GPS_HS"),
        daemon=False,
        name="H->A",
    )
    t_a_h = threading.Thread(
        target=forwarder,
        args=(ser_as_gps_hs, ser_helix, "AS_GPS_HS", "Helix"),
        daemon=False,
        name="A->H",
    )

    t_h_a.start()
    t_a_h.start()

    print("MITM Proxy active. Bridging Helix and AS GPS HS...")

    try:
        while not stop_event.is_set():
            try:
                exc = THREAD_EXCEPTION_QUEUE.get_nowait()
                print("Worker exception:", exc)
                stop_event.set()
                break
            except queue.Empty:
                pass
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()

        for t in (t_h_a, t_a_h):
            if t and t.is_alive():
                t.join(timeout=2)

        # Drain any remaining serial data before closing
        try:
            if ser_helix and getattr(ser_helix, "in_waiting", 0):
                rem = ser_helix.read(ser_helix.in_waiting)
                if rem:
                    put_log(("raw", "Helix->AS_GPS_HS-final", rem))
        except Exception:
            pass

        try:
            if ser_as_gps_hs and getattr(ser_as_gps_hs, "in_waiting", 0):
                rem = ser_as_gps_hs.read(ser_as_gps_hs.in_waiting)
                if rem:
                    put_log(("raw", "AS_GPS_HS->Helix-final", rem))
        except Exception:
            pass

        try:
            if ser_helix:
                ser_helix.close()
        except Exception:
            pass

        try:
            if ser_as_gps_hs:
                ser_as_gps_hs.close()
        except Exception:
            pass

        put_log(LOGGER_SENTINEL)
        if logger_thread.is_alive():
            logger_thread.join(timeout=5)

    print("Stopped.")
    print("Logs saved to:")
    print(" BIN:", LOG_FILE_BIN)
    print(" CSV:", LOG_FILE_CSV)
    print(" TXT:", LOG_FILE_TXT)


if __name__ == "__main__":
    main()
