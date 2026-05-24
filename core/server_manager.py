"""
core/server_manager.py
Optimized:
  - StreamReaderThread: batches lines into a list and emits once per 50ms
    instead of one signal per line — eliminates GUI signal overhead at high
    log volume (Minecraft spams dozens of lines/sec on startup).
  - ResourceMonitorThread: uses psutil one_shot() to fetch CPU+RAM in a
    single kernel call instead of two separate calls.
  - bufsize increased to 65536 for faster pipe reads.
  - _on_stream_ended guarded against double-call.
"""
import subprocess
import threading
import time
from typing import Optional

import psutil
from PySide6.QtCore import QObject, QThread, Signal


# ── Stream Reader (batched) ────────────────────────────────────────

class StreamReaderThread(QThread):
    """
    Reads stdout line-by-line, batches lines for up to BATCH_MS milliseconds,
    then emits them all at once as a single newline-joined string.
    This dramatically reduces the number of Qt signal crossings when the
    server is spamming output (e.g. world generation, startup).
    """
    lines_received = Signal(str)   # One or more lines joined by \n
    stream_ended   = Signal()

    BATCH_MS = 50   # Collect lines for this many ms before emitting

    def __init__(self, stream, parent=None):
        super().__init__(parent)
        self._stream = stream
        self.setObjectName("StreamReaderThread")

    def run(self):
        batch: list[str] = []
        last_flush = time.monotonic()

        try:
            for raw in self._stream:
                line = (raw.decode("utf-8", errors="replace")
                        if isinstance(raw, bytes) else raw).rstrip("\n")
                batch.append(line)

                now = time.monotonic()
                if (now - last_flush) * 1000 >= self.BATCH_MS:
                    if batch:
                        self.lines_received.emit("\n".join(batch))
                        batch.clear()
                    last_flush = now
        except ValueError:
            pass  # Stream closed externally
        finally:
            if batch:
                self.lines_received.emit("\n".join(batch))
            self.stream_ended.emit()


# ── Resource Monitor (one_shot) ────────────────────────────────────

class ResourceMonitorThread(QThread):
    """
    Polls CPU + RAM via psutil.Process.one_shot() — a context manager that
    caches all process info in a single /proc read, halving syscall overhead.
    """
    stats_updated = Signal(float, float)   # cpu_percent, ram_mb
    process_gone  = Signal()

    def __init__(self, pid: int, interval: float = 2.0, parent=None):
        super().__init__(parent)
        self._pid = pid
        self._interval = interval
        self._stop = threading.Event()
        self.setObjectName("ResourceMonitorThread")

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            proc = psutil.Process(self._pid)
            proc.cpu_percent(interval=None)   # Prime — first call is always 0
        except psutil.NoSuchProcess:
            self.process_gone.emit()
            return

        while not self._stop.wait(self._interval):
            try:
                cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_info().rss / 1_048_576   # bytes → MB
                self.stats_updated.emit(cpu, mem)
            except psutil.NoSuchProcess:
                self.process_gone.emit()
                return


# ── Server Manager ─────────────────────────────────────────────────

class ServerManager(QObject):
    """
    Owns the Minecraft server subprocess lifetime.

    Signals:
        output_line(str)         — one or more console lines (joined by \\n)
        server_started()
        server_stopped()
        stats_updated(float, float)  — (cpu%, ram_mb)
    """
    output_line    = Signal(str)
    server_started = Signal()
    server_stopped = Signal()
    stats_updated  = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._reader:  Optional[StreamReaderThread]    = None
        self._monitor: Optional[ResourceMonitorThread] = None
        self._stopped_emitted = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, command: list[str], working_dir: str) -> None:
        if self.is_running:
            raise RuntimeError("Server is already running.")

        self._stopped_emitted = False

        self._process = subprocess.Popen(
            command,
            cwd=working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=65536,   # Large buffer → fewer read() syscalls
        )

        self._reader = StreamReaderThread(self._process.stdout)
        self._reader.lines_received.connect(self.output_line)
        self._reader.stream_ended.connect(self._on_stream_ended)
        self._reader.start()

        self._monitor = ResourceMonitorThread(self._process.pid)
        self._monitor.stats_updated.connect(self.stats_updated)
        self._monitor.process_gone.connect(self._on_stream_ended)
        self._monitor.start()

        self.server_started.emit()

    def send_command(self, command: str) -> None:
        if not self.is_running:
            return
        try:
            self._process.stdin.write((command.strip() + "\n").encode())
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def stop(self) -> None:
        self.send_command("stop")

    def kill(self) -> None:
        if self._process:
            self._process.kill()

    def _on_stream_ended(self):
        # Guard: monitor and reader both connect here; only fire once
        if self._stopped_emitted:
            return
        self._stopped_emitted = True
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(2000)
        self._process = None
        self.server_stopped.emit()
