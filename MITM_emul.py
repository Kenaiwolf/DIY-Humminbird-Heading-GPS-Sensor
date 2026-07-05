#!/usr/bin/env python3  
"""  
MITM serial proxy between Helix and Holybro M9N.  
Injects $GPHDG (2 Hz) and $PTSI160 (1 Hz) with static heading.  
  
Frequencies from captured AS GPS HS log:  
  $GPHDG  : every 500 ms  (2 Hz)  
  $PTSI160: every 1000 ms (1 Hz), immediately after $GPHDG  
  
Pattern per 1000 ms cycle:  
  t=0 ms  : $GPHDG + $PTSI160  
  t=500 ms: $GPHDG only  
  
Requirements: pip install pyserial  
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
M9N_PORT   = "COM10"  
BAUD_RATE  = 38400  
  
# Static injection values (until I2C compass is wired)  
STATIC_HEADING = 222    # integer degrees 0-359  
STATIC_V1      = 0      # PTSI160 field 1 (quality, observed range 3-7)  
STATIC_V2      = 0     # PTSI160 field 2 (gyro/tilt, observed range 0 to -9)  
  
try:  
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  
except NameError:  
    SCRIPT_DIR = os.getcwd()  
  
SESSION_TS   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  
LOG_FILE_BIN = os.path.join(SCRIPT_DIR, f"serial_log_{SESSION_TS}.bin")  
LOG_FILE_CSV = os.path.join(SCRIPT_DIR, f"timestamp_log_{SESSION_TS}.csv")  
LOG_FILE_TXT = os.path.join(SCRIPT_DIR, f"nmea_log_{SESSION_TS}.txt")  
  
log_queue              = queue.Queue(maxsize=20000)  
stop_event             = threading.Event()  
THREAD_EXCEPTION_QUEUE = queue.Queue()  
LOGGER_SENTINEL        = object()  
  
# Shared lock: both M9N->Helix forwarder and injector write to ser_helix  
helix_write_lock = threading.Lock()  
  
  
# ----- Utilities -----  
def now_ts():  
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  
  
def hexlify(data: bytes) -> str:  
    return binascii.hexlify(data).decode("ascii").upper()  
  
def calculate_checksum_bytes(payload: bytes) -> str:  
    c = 0  
    for b in payload:  
        c ^= b  
    return f"{c:02X}"  
  
def build_sentence(payload: str) -> bytes:  
    payload_bytes = payload.encode("ascii")  
    cs = calculate_checksum_bytes(payload_bytes)  
    return b"$" + payload_bytes + b"*" + cs.encode("ascii") + b"\r\n"  
  
def build_gphdg(heading: int) -> bytes:  
    return build_sentence(f"GPHDG,{heading}.0,0.0,E,0.0,E")  
  
def build_ptsi160(v1: int, v2: int, hhh: int) -> bytes:  
    return build_sentence(f"PTSI160,{v1},{v2},{hhh}")  
  
def is_valid_nmea(line: bytes) -> bool:  
    try:  
        if not line.startswith(b"$"):  
            return False  
        if b"*" not in line:  
            return False  
        star_idx = line.rfind(b"*")  
        if star_idx < 2 or len(line) < star_idx + 3:  
            return False  
        body     = line[1:star_idx]  
        expected = calculate_checksum_bytes(body)  
        actual   = line[star_idx + 1:star_idx + 3].decode("ascii", errors="ignore").upper()  
        return expected == actual  
    except Exception:  
        return False  
  
def put_log(item):  
    try:  
        log_queue.put(item, timeout=1.0)  
    except queue.Full:  
        try:  
            log_queue.get_nowait()   # drop oldest to make room  
        except Exception:  
            pass  
        try:  
            log_queue.put_nowait(item)  
        except Exception:  
            pass  
  
  
# ----- Logger thread -----  
def async_logger_worker():  
    try:  
        with open(LOG_FILE_BIN, "ab") as f_bin:  
            with open(LOG_FILE_TXT, "a", encoding="utf-8", errors="replace", buffering=1) as f_txt:  
                with open(LOG_FILE_CSV, "a", newline="", encoding="utf-8", errors="replace", buffering=1) as f_csv:  
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
                                csv_writer.writerow([ts, direction, "raw",  
                                                     f"RAW_LEN={len(data)} HEX={hexlify(data)}"])  
                            elif log_type == "nmea":  
                                decoded = data.decode("ascii", errors="replace").rstrip("\r\n")  
                                f_txt.write(f"[{ts}] [{direction}] {decoded}\n")  
                                csv_writer.writerow([ts, direction, "nmea", decoded])  
                            elif log_type == "note":  
                                msg = str(data)  
                                f_txt.write(f"[{ts}] [{direction}] NOTE: {msg}\n")  
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
  
  
# ----- Buffered serial reader -----  
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
        sentences = []  
        while True:  
            cr = self.buf.find(b"\r\n")  
            lf = self.buf.find(b"\n")  
            if cr == -1 and lf == -1:  
                break  
            if cr != -1 and (lf == -1 or cr <= lf):  
                end = cr + 2  
            else:  
                end = lf + 1  
            sentences.append(bytes(self.buf[:end]))  
            del self.buf[:end]  
        return sentences  
  
    def flush(self):  
        if not self.buf:  
            return b""  
        rem = bytes(self.buf)  
        self.buf.clear()  
        return rem  
  
  
# ----- Forwarding thread -----  
def forwarder(ser_src, ser_dst, name_src, name_dst, dst_lock=None):  
    reader    = SerialBufferReader(ser_src)  
    direction = f"{name_src}->{name_dst}"  
  
    try:  
        while not stop_event.is_set():  
            data = reader.read_available()  
            if not data:  
                continue  
  
            # Log NMEA and raw BEFORE forwarding so a write failure loses nothing  
            try:  
                sentences = reader.feed(data)  
                for s in sentences:  
                    if is_valid_nmea(s):  
                        put_log(("nmea", direction, s))  
                    elif s.startswith(b"$"):  
                        put_log(("note", direction, f"partial/invalid NMEA: {s!r}"))  
            except Exception:  
                pass  
  
            put_log(("raw", direction, data))  
  
            try:  
                if dst_lock:  
                    with dst_lock:  
                        ser_dst.write(data)  
                else:  
                    ser_dst.write(data)  
            except Exception as e:  
                put_log(("note", direction, f"write failed: {e}"))  
                stop_event.set()  
                break  
  
    except Exception as e:  
        THREAD_EXCEPTION_QUEUE.put(e)  
        stop_event.set()  
  
    leftover = reader.flush()  
    if leftover:  
        put_log(("raw", f"{direction}-flush", leftover))  
        if leftover.startswith(b"$"):  
            put_log(("note", f"{direction}-flush",  
                     f"leftover partial NMEA: {leftover!r}"))  
  
  
# ----- Injection thread -----  
# Runs on its own timer — completely independent of M9N data rate.  
# Uses helix_write_lock to avoid interleaving with the M9N->Helix forwarder.  
#  
# Tick pattern (500 ms base):  
#   tick 0: $GPHDG + $PTSI160   (t=0 ms)  
#   tick 1: $GPHDG only         (t=500 ms)  
#   tick 2: $GPHDG + $PTSI160   (t=1000 ms)  
#   ...  
  
def injection_thread(ser_helix):  
    interval = 0.500  
    next_t   = time.perf_counter() + interval  
    tick     = 0  
  
    while not stop_event.is_set():  
        gphdg   = build_gphdg("333")  
        ptsi160 = build_ptsi160(STATIC_V1, STATIC_V2, STATIC_HEADING)  
  
        with helix_write_lock:  
            # $GPHDG every 500 ms  
            put_log(("nmea", "INJ->Helix", gphdg))  
            try:  
                ser_helix.write(gphdg)  
            except Exception as e:  
                put_log(("note", "INJ->Helix", f"GPHDG write failed: {e}"))  
                stop_event.set()  
                return  
  
            # $PTSI160 every 1000 ms (every other tick)  
            if tick % 2 == 0:  
                put_log(("nmea", "INJ->Helix", ptsi160))  
                try:  
                    ser_helix.write(ptsi160)  
                except Exception as e:  
                    put_log(("note", "INJ->Helix", f"PTSI160 write failed: {e}"))  
                    stop_event.set()  
                    return  
  
        tick += 1  
        sleep = next_t - time.perf_counter()  
        if sleep > 0:  
            time.sleep(sleep)  
        next_t += interval   # drift-corrected: accumulate, don't reset  
  
  
# ----- Main -----  
def main():  
    if serial is None:  
        print("pyserial not installed; run: pip install pyserial")  
        return  
  
    print("Log files:")  
    print("  BIN:", LOG_FILE_BIN)  
    print("  CSV:", LOG_FILE_CSV)  
    print("  TXT:", LOG_FILE_TXT)  
    print(f"Injecting: heading={STATIC_HEADING}  V1={STATIC_V1}  V2={STATIC_V2}")  
    print("  $GPHDG  every 500 ms  (2 Hz)")  
    print("  $PTSI160 every 1000 ms (1 Hz)")  
  
    def _signal_handler(signum, frame):  
        stop_event.set()  
  
    signal.signal(signal.SIGINT, _signal_handler)  
    try:  
        signal.signal(signal.SIGTERM, _signal_handler)  
    except Exception:  
        pass  
  
    logger_thread = threading.Thread(target=async_logger_worker,  
                                     daemon=False, name="LoggerThread")  
    logger_thread.start()  
  
    ser_helix = None  
    ser_m9n   = None  
  
    try:  
        ser_helix = serial.Serial(HELIX_PORT, BAUD_RATE,  
                                  timeout=0.05, write_timeout=1.0)  
        ser_m9n   = serial.Serial(M9N_PORT,   BAUD_RATE,  
                                  timeout=0.05, write_timeout=1.0)  
    except Exception as e:  
        print("Port error:", e)  
        stop_event.set()  
        put_log(LOGGER_SENTINEL)  
        logger_thread.join(timeout=5)  
        return  
  
    # Helix->M9N: no lock needed (only this thread writes to ser_m9n)  
    t_h_m = threading.Thread(target=forwarder,  
                              args=(ser_helix, ser_m9n, "Helix", "M9N", None),  
                              daemon=False, name="H->M")  
    # M9N->Helix: uses helix_write_lock shared with injector  
    t_m_h = threading.Thread(target=forwarder,  
                              args=(ser_m9n, ser_helix, "M9N", "Helix", helix_write_lock),  
                              daemon=False, name="M->H")  
    # Injector: independent 500ms timer  
    t_inj = threading.Thread(target=injection_thread,  
                              args=(ser_helix,),  
                              daemon=False, name="Injector")  
  
    t_h_m.start()  
    t_m_h.start()  
    t_inj.start()  
  
    print("MITM active — Helix <-> M9N with heading injection. Ctrl+C to stop.")  
  
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
  
        for t in (t_h_m, t_m_h, t_inj):  
            if t and t.is_alive():  
                t.join(timeout=2)  
  
        for ser, label in ((ser_helix, "Helix->M9N-final"),  
                           (ser_m9n,   "M9N->Helix-final")):  
            try:  
                if ser and getattr(ser, "in_waiting", 0):  
                    rem = ser.read(ser.in_waiting)  
                    if rem:  
                        put_log(("raw", label, rem))  
            except Exception:  
                pass  
  
        for ser in (ser_helix, ser_m9n):  
            try:  
                if ser:  
                    ser.close()  
            except Exception:  
                pass  
  
        put_log(LOGGER_SENTINEL)  
        if logger_thread.is_alive():  
            logger_thread.join(timeout=5)  
  
    print("Stopped. Logs saved.")  
  
  
if __name__ == "__main__":  
    main()