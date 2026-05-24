"""
ui/wizard_window.py — MCServerMaker Setup Wizard

Page order:
  0  DEPS     — dependency checker (new splash screen)
  1  ENV      — Python/Java version check (auto-advances)
  2  LANDING  — New / Existing / Browse
  3  FOLDER
  4  JAR
  5  SEED
  6  INIT
  7  EULA
  8  RAM
  9  LAUNCH
  10 EXISTING
"""

import os, sys, subprocess, json, importlib
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QSlider, QButtonGroup,
    QFileDialog, QFrame, QStackedWidget, QPlainTextEdit, QScrollArea,
    QProgressBar, QSizePolicy,
)
from PySide6.QtGui import QFont

from core.config import ServerConfig, load_config, save_config
from core.java_detector import find_java_installations, MIN_JAVA_VERSION


# ── Dependency manifest ────────────────────────────────────────────
# Each entry: (display_name, import_name, pip_name, why_needed)
DEPENDENCIES = [
    ("PySide6",   "PySide6",   "PySide6>=6.6.0",   "GUI framework"),
    ("psutil",    "psutil",    "psutil>=5.9.0",     "CPU & RAM monitoring"),
    ("requests",  "requests",  "requests>=2.31.0",  "HTTP downloads"),
]

PRESET_SEEDS = [
    ("Epik mountin",   "3257840388"),
    ("Plains next to ice spikes?",    "1669320484"),
    ("Sum badlands biome",  "110918009"),
    ("Cherry Blossom",     "-1813745601"),
    ("NOT inside a Doritos bag!",      "3227028068"),
    ("Village.",   "2151901553968352745"),
    ("Sum random seed",   "7749012223078990226"),
    ("Insane Valleys",    "903158928917910"),
]

SAVED_SERVERS_FILE = os.path.expanduser("~/.config/MCServerMaker/servers.json")


def load_saved_servers() -> list[dict]:
    if not os.path.isfile(SAVED_SERVERS_FILE):
        return []
    try:
        with open(SAVED_SERVERS_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_server_to_list(name: str, config: "ServerConfig"):
    os.makedirs(os.path.dirname(SAVED_SERVERS_FILE), exist_ok=True)
    servers = load_saved_servers()
    for s in servers:
        if s["directory"] == config.server_directory:
            s.update({"name": name, "jar": config.server_jar_path,
                       "java": config.java_path})
            break
    else:
        servers.append({"name": name, "directory": config.server_directory,
                        "jar": config.server_jar_path, "java": config.java_path})
    with open(SAVED_SERVERS_FILE, "w") as f:
        json.dump(servers, f, indent=2)

def find_jar_in_folder(folder: str) -> Optional[str]:
    try:
        jars = [f for f in os.listdir(folder) if f.endswith(".jar")]
        if not jars: return None
        if "server.jar" in jars: return os.path.join(folder, "server.jar")
        return os.path.join(folder, jars[0])
    except Exception:
        return None


# ── Background workers ─────────────────────────────────────────────

class DepCheckThread(QThread):
    """Checks every dependency and emits per-item results."""
    item_result = Signal(str, bool, str)   # (name, ok, detail)
    all_done    = Signal(bool)             # True = all passed

    def run(self):
        all_ok = True

        # Python version
        major, minor = sys.version_info.major, sys.version_info.minor
        py_ok = (major == 3 and minor >= 10)
        detail = f"{major}.{minor}.{sys.version_info.micro}"
        self.item_result.emit("Python 3.10+", py_ok, detail)
        if not py_ok: all_ok = False

        # Java
        installs = find_java_installations()
        compatible = [j for j in installs if j.version >= MIN_JAVA_VERSION]
        if compatible:
            best = compatible[0]
            self.item_result.emit(
                f"Java {MIN_JAVA_VERSION}+", True,
                f"Java {best.version} at {best.path}")
        elif installs:
            best = installs[0]
            self.item_result.emit(
                f"Java {MIN_JAVA_VERSION}+", False,
                f"Found Java {best.version} — need {MIN_JAVA_VERSION}+")
            all_ok = False
        else:
            self.item_result.emit(f"Java {MIN_JAVA_VERSION}+", False, "Not found")
            all_ok = False

        # Python packages
        for display, import_name, pip_name, reason in DEPENDENCIES:
            try:
                mod = importlib.import_module(import_name)
                version = getattr(mod, "__version__", "installed")
                self.item_result.emit(display, True, f"v{version} — {reason}")
            except ImportError:
                self.item_result.emit(display, False,
                                      f"Not installed — pip install {pip_name}")
                all_ok = False

        self.all_done.emit(all_ok)


class EnvCheckThread(QThread):
    result_ready = Signal(dict)
    def run(self):
        major, minor = sys.version_info.major, sys.version_info.minor
        installs = find_java_installations()
        compatible = [j for j in installs if j.version >= MIN_JAVA_VERSION]
        if compatible:
            best = compatible[0]
            jv = {"version": best.version_string, "major": best.version,
                  "path": best.path, "ok": True}
        elif installs:
            best = installs[0]
            jv = {"version": best.version_string, "major": best.version,
                  "path": best.path, "ok": False}
        else:
            jv = {"version": None, "major": 0, "path": None, "ok": False}
        self.result_ready.emit({
            "python": {"version": f"{major}.{minor}.{sys.version_info.micro}",
                       "ok": (major == 3 and minor >= 10)},
            "java": jv,
        })


class EulaGeneratorThread(QThread):
    line_out   = Signal(str)
    eula_found = Signal(bool)
    def __init__(self, java_path, jar_path, server_dir):
        super().__init__()
        self._java, self._jar, self._dir = java_path, jar_path, server_dir
    def run(self):
        import time
        eula_path = os.path.join(self._dir, "eula.txt")
        cmd = [self._java, "-Xmx512M", "-jar", self._jar, "--nogui"]
        self.line_out.emit(f"[MCServerMaker] Running: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(cmd, cwd=self._dir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL)
            start = time.time()
            for raw in proc.stdout:
                self.line_out.emit(raw.decode("utf-8", errors="replace").rstrip())
                if os.path.isfile(eula_path): break
                if time.time() - start > 30:
                    self.line_out.emit("[MCServerMaker] Timeout.")
                    break
            proc.kill(); proc.wait()
        except Exception as e:
            self.line_out.emit(f"[MCServerMaker] Error: {e}")
        self.eula_found.emit(os.path.isfile(eula_path))


# ── Helpers ────────────────────────────────────────────────────────

def _divider():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#313244; margin:2px 0;"); return f

def _h2(text):
    l = QLabel(text)
    l.setStyleSheet("font-size:16px; font-weight:bold; color:#cdd6f4;"); return l

def _caption(text):
    l = QLabel(text); l.setWordWrap(True)
    l.setStyleSheet("color:#6c7086; font-size:12px;"); return l

CONTINUE_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 #89b4fa, stop:1 #cba6f7);
        color:#1e1e2e; font-size:14px; font-weight:bold;
        border:none; border-radius:8px; padding:0 20px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 #b4d0fb, stop:1 #d9b8f9);
    }
    QPushButton:disabled { background:#313244; color:#45475a; }
"""

BACK_STYLE = """
    QPushButton {
        background:#313244; color:#cdd6f4;
        border:1px solid #45475a; border-radius:8px;
        font-size:13px; padding:0 16px;
    }
    QPushButton:hover { background:#45475a; }
"""

# ── Page indices ───────────────────────────────────────────────────
PAGE_DEPS     = 0
PAGE_ENV      = 1
PAGE_LANDING  = 2
PAGE_FOLDER   = 3
PAGE_JAR      = 4
PAGE_SEED     = 5
PAGE_INIT     = 6
PAGE_EULA     = 7
PAGE_RAM      = 8
PAGE_LAUNCH   = 9
PAGE_EXISTING = 10

TOTAL_NEW      = 7
TOTAL_EXISTING = 2

BACK_MAP_NEW = {
    PAGE_FOLDER:   PAGE_LANDING,
    PAGE_JAR:      PAGE_FOLDER,
    PAGE_SEED:     PAGE_JAR,
    PAGE_INIT:     PAGE_SEED,
    PAGE_EULA:     PAGE_INIT,
    PAGE_RAM:      PAGE_EULA,
    PAGE_LAUNCH:   PAGE_RAM,
}
BACK_MAP_EXISTING = {
    PAGE_EXISTING: PAGE_LANDING,
    PAGE_LAUNCH:   PAGE_EXISTING,
}


# ── Wizard Window ──────────────────────────────────────────────────

class WizardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MCServerMaker")
        self.setMinimumSize(580, 560)
        self.resize(890, 680)
        self.config = load_config()
        self._java_path: Optional[str] = self.config.java_path or "java"
        self._flow = "new"
        self._launch_mode = "test"
        self._current_page = PAGE_DEPS
        self._build_shell()
        self._show_page(PAGE_DEPS)
        self._run_dep_check()

    # ── Shell ──────────────────────────────────────────────────────

    def _build_shell(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet("background:#181825;")
        header.setFixedHeight(52)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(24, 8, 24, 8); hl.setSpacing(4)
        self._step_label = QLabel("Checking dependencies…")
        self._step_label.setStyleSheet("color:#6c7086; font-size:11px;")
        hl.addWidget(self._step_label)
        self._progress = QProgressBar()
        self._progress.setRange(0, TOTAL_NEW); self._progress.setValue(0)
        self._progress.setTextVisible(False); self._progress.setFixedHeight(5)
        self._progress.setStyleSheet("""
            QProgressBar{background:#313244;border-radius:2px;border:none;}
            QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #89b4fa,stop:1 #cba6f7);border-radius:2px;}
        """)
        hl.addWidget(self._progress)
        outer.addWidget(header)

        # Stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:#1e1e2e;")
        outer.addWidget(self._stack, stretch=1)

        # Bottom bar
        bar = QWidget()
        bar.setStyleSheet("background:#181825; border-top:2px solid #89b4fa;")
        bar.setFixedHeight(68)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 12, 24, 12); bl.setSpacing(10)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedHeight(42); self._back_btn.setMinimumWidth(100)
        self._back_btn.setStyleSheet(BACK_STYLE)
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self._on_back)
        bl.addWidget(self._back_btn)

        self._err_label = QLabel("")
        self._err_label.setStyleSheet("color:#f38ba8; font-size:12px;")
        bl.addWidget(self._err_label, stretch=1)

        self._continue_btn = QPushButton("Continue →")
        self._continue_btn.setFixedHeight(42); self._continue_btn.setMinimumWidth(160)
        self._continue_btn.setEnabled(False)
        self._continue_btn.setStyleSheet(CONTINUE_STYLE)
        self._continue_btn.clicked.connect(self._on_continue)
        bl.addWidget(self._continue_btn)
        outer.addWidget(bar)

        for page in [
            self._build_page_deps(),      # 0
            self._build_page_env(),       # 1
            self._build_page_landing(),   # 2
            self._build_page_folder(),    # 3
            self._build_page_jar(),       # 4
            self._build_page_seed(),      # 5
            self._build_page_init(),      # 6
            self._build_page_eula(),      # 7
            self._build_page_ram(),       # 8
            self._build_page_launch(),    # 9
            self._build_page_existing(),  # 10
        ]:
            self._stack.addWidget(page)

    def _content_page(self):
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 16); lay.setSpacing(12)
        scroll = QScrollArea(); scroll.setWidget(inner); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        wrap = QWidget(); wrap.setStyleSheet("background:#1e1e2e;")
        wl = QVBoxLayout(wrap); wl.setContentsMargins(0,0,0,0); wl.addWidget(scroll)
        return wrap, lay

    # ── Navigation ─────────────────────────────────────────────────

    def _show_page(self, index: int):
        self._current_page = index
        self._stack.setCurrentIndex(index)
        self._err_label.setText("")

        back_map = BACK_MAP_NEW if self._flow == "new" else BACK_MAP_EXISTING
        self._back_btn.setVisible(index in back_map)

        if index == PAGE_DEPS:
            self._step_label.setText("Checking dependencies…")
            self._progress.setValue(0)
            self._continue_btn.setVisible(True)
            self._continue_btn.setEnabled(False)
            return

        if index == PAGE_ENV:
            self._step_label.setText("Checking environment…")
            self._progress.setValue(0)
            self._continue_btn.setVisible(True)
            self._continue_btn.setEnabled(False)
            return

        if index == PAGE_LANDING:
            self._step_label.setText("Welcome to MCServerMaker")
            self._progress.setValue(0)
            self._continue_btn.setVisible(False)
            return

        if self._flow == "new":
            step_map = {PAGE_FOLDER:1, PAGE_JAR:2, PAGE_SEED:3,
                        PAGE_INIT:4, PAGE_EULA:5, PAGE_RAM:6, PAGE_LAUNCH:7}
            n = step_map.get(index, 0)
            self._step_label.setText(f"New server — step {n} of {TOTAL_NEW}")
            self._progress.setRange(0, TOTAL_NEW); self._progress.setValue(n)
        else:
            step_map = {PAGE_EXISTING:1, PAGE_LAUNCH:2}
            n = step_map.get(index, 0)
            self._step_label.setText(f"Existing server — step {n} of {TOTAL_EXISTING}")
            self._progress.setRange(0, TOTAL_EXISTING); self._progress.setValue(n)

        self._continue_btn.setVisible(True)
        cfg = {
            PAGE_FOLDER:   ("Continue →",          True),
            PAGE_JAR:      ("Continue →",          True),
            PAGE_SEED:     ("Continue →",          True),
            PAGE_INIT:     ("▶  Run init",          True),
            PAGE_EULA:     ("Continue →",          False),
            PAGE_RAM:      ("Continue →",          True),
            PAGE_LAUNCH:   ("Launch Server →", True),
            PAGE_EXISTING: ("Continue →",          False),
        }
        label, enabled = cfg.get(index, ("Continue →", True))
        self._continue_btn.setText(label)
        self._continue_btn.setEnabled(enabled)

    def _on_back(self):
        self._err_label.setText("")
        back_map = BACK_MAP_NEW if self._flow == "new" else BACK_MAP_EXISTING
        target = back_map.get(self._current_page, PAGE_LANDING)
        if target == PAGE_LANDING: self._flow = "new"
        self._show_page(target)

    def _on_continue(self):
        p = self._current_page
        if   p == PAGE_DEPS:     self._show_page(PAGE_ENV); self._run_env_check()
        elif p == PAGE_FOLDER:   self._validate_folder()
        elif p == PAGE_JAR:      self._validate_jar()
        elif p == PAGE_SEED:     self._apply_seed_and_next()
        elif p == PAGE_INIT:     self._run_eula_gen()
        elif p == PAGE_EULA:     self._validate_eula()
        elif p == PAGE_RAM:      self._show_page(PAGE_LAUNCH)
        elif p == PAGE_LAUNCH:   self._finish()
        elif p == PAGE_EXISTING: self._validate_existing()

    # ══════════════════════════════════════════════════════════════
    #  PAGE 0 — Dependencies
    # ══════════════════════════════════════════════════════════════

    def _build_page_deps(self):
        page = QWidget(); page.setStyleSheet("background:#1e1e2e;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 32, 40, 24); lay.setSpacing(0)

        # Title area
        title = QLabel("MCServerMaker")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:24px;font-weight:bold;color:#cdd6f4;")
        lay.addWidget(title)
        lay.addSpacing(4)
        sub = QLabel("All dependancies are checked locally on your machine.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#6c7086;font-size:12px;")
        lay.addWidget(sub)
        lay.addSpacing(20)

        # Dependency rows container
        dep_container = QWidget()
        dep_container.setStyleSheet(
            "background:#181825;border-radius:10px;padding:4px;")
        self._dep_layout = QVBoxLayout(dep_container)
        self._dep_layout.setContentsMargins(16, 12, 16, 12)
        self._dep_layout.setSpacing(0)
        lay.addWidget(dep_container)

        # Placeholder rows — filled by _run_dep_check
        total_deps = 2 + len(DEPENDENCIES)  # Python + Java + packages
        self._dep_rows: dict[str, tuple] = {}  # name → (icon_lbl, detail_lbl)
        for i in range(total_deps):
            row = QWidget()
            row.setStyleSheet(
                "border-bottom:1px solid #313244;" if i < total_deps - 1 else "")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 10, 0, 10); rl.setSpacing(12)
            spinner = QLabel("⏳")
            spinner.setFixedWidth(22)
            spinner.setStyleSheet("font-size:15px;")
            rl.addWidget(spinner)
            name_lbl = QLabel("—")
            name_lbl.setStyleSheet("font-weight:bold;font-size:13px;color:#cdd6f4;")
            name_lbl.setMinimumWidth(140)
            rl.addWidget(name_lbl)
            detail_lbl = QLabel("")
            detail_lbl.setStyleSheet("color:#6c7086;font-size:12px;")
            detail_lbl.setWordWrap(True)
            rl.addWidget(detail_lbl, stretch=1)
            self._dep_layout.addWidget(row)

        lay.addSpacing(16)

        # Install hint box (hidden until needed)
        self._dep_hint = QLabel("")
        self._dep_hint.setWordWrap(True)
        self._dep_hint.setStyleSheet(
            "background:#181825;border:1px solid #f38ba8;border-radius:8px;"
            "color:#f9e2af;font-family:monospace;font-size:11px;padding:12px;")
        self._dep_hint.setVisible(False)
        lay.addWidget(self._dep_hint)

        lay.addStretch()

        # Retry button (hidden until needed)
        self._dep_retry_btn = QPushButton("🔄  Re-check")
        self._dep_retry_btn.setStyleSheet(BACK_STYLE)
        self._dep_retry_btn.setFixedHeight(38)
        self._dep_retry_btn.setVisible(False)
        self._dep_retry_btn.clicked.connect(self._run_dep_check)
        lay.addWidget(self._dep_retry_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return page

    def _run_dep_check(self):
        # Reset all rows to spinner state
        for i in range(self._dep_layout.count()):
            row_widget = self._dep_layout.itemAt(i).widget()
            if not row_widget: continue
            rl = row_widget.layout()
            rl.itemAt(0).widget().setText("⏳")
            rl.itemAt(1).widget().setText("—")
            rl.itemAt(2).widget().setText("")

        self._dep_row_index = 0
        self._dep_hint.setVisible(False)
        self._dep_retry_btn.setVisible(False)
        self._continue_btn.setEnabled(False)
        self._dep_hints_list: list[str] = []

        self._dep_thread = DepCheckThread()
        self._dep_thread.item_result.connect(self._on_dep_item)
        self._dep_thread.all_done.connect(self._on_dep_all_done)
        self._dep_thread.start()

    def _on_dep_item(self, name: str, ok: bool, detail: str):
        idx = self._dep_row_index
        self._dep_row_index += 1
        if idx >= self._dep_layout.count(): return

        row_widget = self._dep_layout.itemAt(idx).widget()
        if not row_widget: return
        rl = row_widget.layout()

        icon_lbl   = rl.itemAt(0).widget()
        name_lbl   = rl.itemAt(1).widget()
        detail_lbl = rl.itemAt(2).widget()

        icon_lbl.setText("✅" if ok else "❌")
        name_lbl.setText(name)
        name_lbl.setStyleSheet(
            f"font-weight:bold;font-size:13px;"
            f"color:{'#a6e3a1' if ok else '#f38ba8'};")
        detail_lbl.setText(detail)

        if not ok:
            self._dep_hints_list.append(detail)

    def _on_dep_all_done(self, all_ok: bool):
        if all_ok:
            self._continue_btn.setEnabled(True)
            self._continue_btn.setText("Continue →")
        else:
            self._dep_hint.setText(
                "Some dependencies are missing. Run this in your terminal:\n\n"
                "  source venv/bin/activate\n"
                "  pip install -r requirements.txt\n\n"
                "Then click Re-check.")
            self._dep_hint.setVisible(True)
            self._dep_retry_btn.setVisible(True)
            self._continue_btn.setText("⚠️  Fix issues above first")
            self._continue_btn.setEnabled(False)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 1 — Env check (auto-advances)
    # ══════════════════════════════════════════════════════════════

    def _build_page_env(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("🔍  Checking environment…"))
        self._env_py   = QLabel("Python: scanning…")
        self._env_java = QLabel("Java:   scanning…")
        lay.addWidget(self._env_py); lay.addWidget(self._env_java)
        self._env_err_box = QLabel("")
        self._env_err_box.setWordWrap(True)
        self._env_err_box.setStyleSheet(
            "background:#181825;padding:10px;border-radius:5px;"
            "color:#f9e2af;font-family:monospace;font-size:11px;")
        self._env_err_box.setVisible(False)
        lay.addWidget(self._env_err_box); lay.addStretch(); return page

    def _run_env_check(self):
        self._env_thread = EnvCheckThread()
        self._env_thread.result_ready.connect(self._on_env_result)
        self._env_thread.start()

    def _on_env_result(self, result):
        py, jv = result["python"], result["java"]
        self._env_py.setText(f"Python: ✅ {py['version']}" if py["ok"]
                             else f"Python: ❌ {py['version']} (need 3.10+)")
        if jv["ok"]:
            self._env_java.setText(f"Java:   ✅ Java {jv['major']} ({jv['version']})")
            self._java_path = jv["path"]
        else:
            self._env_java.setText(
                f"Java:   ❌ {'Java '+str(jv['major'])+' found' if jv['version'] else 'Not found'} (need 21+)")
        if py["ok"] and jv["ok"]:
            self._show_page(PAGE_LANDING)
        else:
            lines = []
            if not py["ok"]:
                lines += ["sudo apt install python3.12","sudo dnf install python3.12",""]
            if not jv["ok"]:
                lines += ["sudo apt install openjdk-21-jdk",
                          "sudo dnf install java-21-openjdk"]
            self._env_err_box.setText("\n".join(lines))
            self._env_err_box.setVisible(True)
            self._continue_btn.setText("⚠️  Fix issues above first")
            self._continue_btn.setEnabled(False)
            self._continue_btn.setVisible(True)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 2 — Landing
    # ══════════════════════════════════════════════════════════════

    def _build_page_landing(self):
        page = QWidget(); page.setStyleSheet("background:#1e1e2e;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(48, 32, 48, 32); lay.setSpacing(12)
        lay.addStretch()

        title = QLabel("MCServerMaker")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:24px;font-weight:bold;color:#cdd6f4;")
        lay.addWidget(title)
        sub = QLabel("What would you like to do?")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#6c7086;font-size:13px;")
        lay.addWidget(sub)
        lay.addSpacing(10)

        new_btn = QPushButton(
            "New Server\n\n     Make a brand new server")
        new_btn.setMinimumHeight(90)
        new_btn.setStyleSheet(self._card_style("#1e3a5f","#89b4fa"))
        new_btn.clicked.connect(self._start_new_flow)
        lay.addWidget(new_btn)

        saved_btn = QPushButton(
            "Open Saved Server\n\n     Pick from previously set up servers")
        saved_btn.setMinimumHeight(90)
        saved_btn.setStyleSheet(self._card_style("#1e2e1e","#a6e3a1"))
        saved_btn.clicked.connect(self._start_existing_flow)
        lay.addWidget(saved_btn)

        folder_btn = QPushButton(
            "Open Server Folder\n\n     Browse to any existing server folder")
        folder_btn.setMinimumHeight(90)
        folder_btn.setStyleSheet(self._card_style("#2e1e3a","#cba6f7"))
        folder_btn.clicked.connect(self._start_folder_browse_flow)
        lay.addWidget(folder_btn)

        lay.addStretch(); return page

    def _card_style(self, bg, border):
        return (f"QPushButton{{background:{bg};border:2px solid {border};"
                f"border-radius:12px;color:#cdd6f4;text-align:left;"
                f"padding:16px 20px;font-size:13px;}}"
                f"QPushButton:hover{{border-color:#ffffff44;background:{bg}dd;}}"
                f"QPushButton:checked{{border-color:#89b4fa;background:{bg}cc;"
                f"color:#89b4fa;font-weight:bold;}}")

    def _start_new_flow(self):
        self._flow = "new"; self._show_page(PAGE_FOLDER)

    def _start_existing_flow(self):
        self._flow = "existing"
        self._refresh_saved_servers(); self._show_page(PAGE_EXISTING)

    def _start_folder_browse_flow(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Server Folder", os.path.expanduser("~"))
        if not folder: return
        jar = find_jar_in_folder(folder)
        if not jar:
            jar, _ = QFileDialog.getOpenFileName(
                self, "Select server.jar", folder,
                "JAR Files (*.jar);;All Files (*)")
            if not jar: return
        self.config.server_directory = folder
        self.config.server_jar_path  = jar
        self.config.java_path        = self._java_path or "java"
        self._flow = "existing"
        self._show_page(PAGE_LAUNCH)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 3 — Folder
    # ══════════════════════════════════════════════════════════════

    def _build_page_folder(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("📁  Select server folder"))
        lay.addWidget(_caption("Where your world and config files will live."))
        lay.addWidget(_divider())
        row = QHBoxLayout()
        self._folder_edit = QLineEdit(self.config.server_directory)
        self._folder_edit.setPlaceholderText("/home/you/minecraft-server")
        row.addWidget(self._folder_edit)
        btn = QPushButton("Browse…"); btn.clicked.connect(self._browse_folder)
        row.addWidget(btn); lay.addLayout(row); lay.addStretch(); return page

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Server Folder", os.path.expanduser("~"))
        if path: self._folder_edit.setText(path)

    def _validate_folder(self):
        path = self._folder_edit.text().strip()
        if not path:
            self._err_label.setText("⚠️  Please select a folder."); return
        os.makedirs(path, exist_ok=True)
        self.config.server_directory = path; self._show_page(PAGE_JAR)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 4 — JAR
    # ══════════════════════════════════════════════════════════════

    def _build_page_jar(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("📦  Select server .jar"))
        lay.addWidget(_caption("Point to your vanilla Minecraft server .jar file."))
        link = QLabel("🌐 <a href='https://www.minecraft.net/en-us/download/server'"
                      " style='color:#89b4fa;'>Download from minecraft.net</a>")
        link.setOpenExternalLinks(True); lay.addWidget(link)
        lay.addWidget(_divider())
        row = QHBoxLayout()
        self._jar_edit = QLineEdit(self.config.server_jar_path)
        self._jar_edit.setPlaceholderText("/home/you/Downloads/server.jar")
        row.addWidget(self._jar_edit)
        btn = QPushButton("Browse…"); btn.clicked.connect(self._browse_jar)
        row.addWidget(btn); lay.addLayout(row); lay.addStretch(); return page

    def _browse_jar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select server.jar", os.path.expanduser("~"),
            "JAR Files (*.jar);;All Files (*)")
        if path: self._jar_edit.setText(path)

    def _validate_jar(self):
        path = self._jar_edit.text().strip()
        if not path or not os.path.isfile(path):
            self._err_label.setText("⚠️  File not found."); return
        self.config.server_jar_path = path; self._show_page(PAGE_SEED)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 5 — Seed
    # ══════════════════════════════════════════════════════════════

    def _build_page_seed(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("🌍  Choose a world seed"))
        lay.addWidget(_caption("Pick a preset or type your own. Leave blank for random."))
        lay.addWidget(_divider())
        lay.addWidget(QLabel("Preset seeds:"))
        grid = QGridLayout(); grid.setSpacing(8)
        self._seed_btn_group = QButtonGroup(self); self._seed_btn_group.setExclusive(True)
        for i, (label, val) in enumerate(PRESET_SEEDS):
            btn = QPushButton(label); btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton{background:#313244;color:#cdd6f4;border:2px solid #45475a;
                    border-radius:8px;padding:8px 6px;font-size:12px;}
                QPushButton:hover{border-color:#89b4fa;background:#3d3f54;}
                QPushButton:checked{border-color:#89b4fa;background:#1e3a5f;
                    color:#89b4fa;font-weight:bold;}
            """)
            btn.clicked.connect(lambda _, v=val: self._on_preset_clicked(v))
            self._seed_btn_group.addButton(btn, i)
            grid.addWidget(btn, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addWidget(_divider())
        row = QHBoxLayout(); row.addWidget(QLabel("Custom seed:"))
        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("Type any seed (or leave blank for random)")
        self._seed_input.textEdited.connect(self._on_custom_seed_typed)
        row.addWidget(self._seed_input); lay.addLayout(row)
        self._seed_preview = QLabel("🎲  Random seed — a surprise world!")
        self._seed_preview.setStyleSheet("color:#a6e3a1;font-size:12px;font-style:italic;")
        lay.addWidget(self._seed_preview); lay.addStretch(); return page

    def _on_preset_clicked(self, val):
        self._seed_input.setText(val)
        self._seed_preview.setText(f"🌍  Seed: {val}")

    def _on_custom_seed_typed(self, text):
        checked = self._seed_btn_group.checkedButton()
        if checked:
            self._seed_btn_group.setExclusive(False)
            checked.setChecked(False)
            self._seed_btn_group.setExclusive(True)
        self._seed_preview.setText(
            f"🌍  Seed: {text.strip()}" if text.strip()
            else "🎲  Random seed — a surprise world!")

    def _apply_seed_and_next(self):
        self.config._pending_seed = self._seed_input.text().strip()
        self._show_page(PAGE_INIT)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 6 — Init
    # ══════════════════════════════════════════════════════════════

    def _build_page_init(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("⚙️  Initialising server…"))
        lay.addWidget(_caption(
            "Click 'Run init' — the server runs briefly to generate "
            "eula.txt and server.properties, then stops automatically."))
        lay.addWidget(_divider())
        self._init_console = QPlainTextEdit()
        self._init_console.setReadOnly(True); self._init_console.setMaximumBlockCount(200)
        f = QFont("Monospace", 9); f.setStyleHint(QFont.StyleHint.TypeWriter)
        self._init_console.setFont(f)
        self._init_console.setStyleSheet(
            "background:#0d0d1a;color:#a6adc8;"
            "border:1px solid #313244;border-radius:4px;")
        self._init_console.setFixedHeight(150)
        lay.addWidget(self._init_console)
        self._init_status = QLabel(""); lay.addWidget(self._init_status)
        lay.addStretch(); return page

    def _run_eula_gen(self):
        self._continue_btn.setEnabled(False); self._continue_btn.setText("Running…")
        self._back_btn.setEnabled(False); self._init_console.clear()
        self._init_status.setText("Running — please wait…")
        self._init_status.setStyleSheet("color:#f9e2af;")
        self._eula_thread = EulaGeneratorThread(
            self._java_path or "java",
            self.config.server_jar_path, self.config.server_directory)
        self._eula_thread.line_out.connect(self._init_console.appendPlainText)
        self._eula_thread.eula_found.connect(self._on_eula_gen_done)
        self._eula_thread.start()

    def _on_eula_gen_done(self, found):
        self._back_btn.setEnabled(True)
        if found:
            self._init_status.setText("✅  Generated! Patching seed…")
            self._init_status.setStyleSheet("color:#a6e3a1;")
            self._patch_seed(); self._show_page(PAGE_EULA)
        else:
            self._init_status.setText("⚠️  eula.txt not found — check output.")
            self._init_status.setStyleSheet("color:#f38ba8;")
            self._continue_btn.setText("▶  Retry"); self._continue_btn.setEnabled(True)

    def _patch_seed(self):
        seed = getattr(self.config, "_pending_seed", "")
        if not seed: return
        props = os.path.join(self.config.server_directory, "server.properties")
        if not os.path.isfile(props): return
        with open(props) as f: lines = f.readlines()
        with open(props, "w") as f:
            found = False
            for line in lines:
                if line.startswith("level-seed="):
                    f.write(f"level-seed={seed}\n"); found = True
                else: f.write(line)
            if not found: f.write(f"level-seed={seed}\n")

    # ══════════════════════════════════════════════════════════════
    #  PAGE 7 — EULA
    # ══════════════════════════════════════════════════════════════

    def _build_page_eula(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("Minecraft EULA"))
        lay.addWidget(_caption("Mojang requires you to accept their EULA."))
        link = QLabel("<a href='https://aka.ms/MinecraftEULA' style='color:#89b4fa;'>"
                      "Read the EULA →</a>")
        link.setOpenExternalLinks(True); lay.addWidget(link)
        lay.addWidget(_divider())
        self._eula_check = QCheckBox("I have read and agree to the Minecraft EULA")
        self._eula_check.stateChanged.connect(
            lambda s: self._continue_btn.setEnabled(bool(s)))
        lay.addWidget(self._eula_check); lay.addStretch(); return page

    def _validate_eula(self):
        if not self._eula_check.isChecked():
            self._err_label.setText("You must accept the EULA."); return
        eula_path = os.path.join(self.config.server_directory, "eula.txt")
        with open(eula_path, "w") as f: f.write("# Accepted via MCServerMaker\neula=true\n")
        self.config.eula_accepted = True; self._show_page(PAGE_RAM)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 8 — RAM
    # ══════════════════════════════════════════════════════════════

    def _build_page_ram(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("RAM Allocation"))
        lay.addWidget(_caption("Set how much RAM the server can use."))
        lay.addWidget(_divider())
        min_row = QHBoxLayout(); min_row.addWidget(QLabel("Min (-Xms):"))
        self._min_slider = QSlider(Qt.Orientation.Horizontal)
        self._min_slider.setRange(512, 8192); self._min_slider.setSingleStep(256)
        self._min_slider.setValue(self.config.ram_min_mb)
        min_row.addWidget(self._min_slider)
        self._min_lbl = QLabel(f"{self.config.ram_min_mb} MB"); self._min_lbl.setMinimumWidth(68)
        min_row.addWidget(self._min_lbl); lay.addLayout(min_row)
        max_row = QHBoxLayout(); max_row.addWidget(QLabel("Max (-Xmx):"))
        self._max_slider = QSlider(Qt.Orientation.Horizontal)
        self._max_slider.setRange(512, 16384); self._max_slider.setSingleStep(256)
        self._max_slider.setValue(self.config.ram_max_mb)
        max_row.addWidget(self._max_slider)
        self._max_lbl = QLabel(f"{self.config.ram_max_mb} MB"); self._max_lbl.setMinimumWidth(68)
        max_row.addWidget(self._max_lbl); lay.addLayout(max_row)
        self._min_slider.valueChanged.connect(lambda v: self._min_lbl.setText(f"{v} MB"))
        self._max_slider.valueChanged.connect(lambda v: self._max_lbl.setText(f"{v} MB"))
        self._flags_preview = QLabel("")
        self._flags_preview.setStyleSheet(
            "background:#181825;padding:10px;border-radius:4px;"
            "color:#a6e3a1;font-family:monospace;font-size:11px;")
        lay.addWidget(self._flags_preview)
        self._min_slider.valueChanged.connect(self._update_flags)
        self._max_slider.valueChanged.connect(self._update_flags)
        self._update_flags(); lay.addStretch(); return page

    def _update_flags(self):
        xms = self._min_slider.value(); xmx = self._max_slider.value()
        self._flags_preview.setText(
            f"java  -Xms{xms}M  -Xmx{xmx}M  -jar  server.jar  --nogui")

    # ══════════════════════════════════════════════════════════════
    #  PAGE 9 — Launch mode
    # ══════════════════════════════════════════════════════════════

    # ── PAGE 8: Launch Mode ────────────────────────────────────────

    def _build_page_launch(self):
        page = QWidget(); page.setStyleSheet("background:#1e1e2e;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 32, 40, 24)
        lay.setSpacing(16)
        lay.addWidget(_h2("Choose launch mode"))
        lay.addWidget(_caption(
            "How do you want to start the server?"))
        lay.addWidget(_divider())

        # Use a Button Group to handle the exclusive "checked" state automatically
        self._launch_group = QButtonGroup(self)
        self._launch_group.setExclusive(True)

        # Test mode card
        self._test_card = QPushButton()
        self._test_card.setCheckable(True)
        self._test_card.setAutoExclusive(True)
        self._test_card.setMinimumHeight(100)
        self._test_card.setStyleSheet(self._card_style("#313244", "#45475a"))
        self._test_card.setText(
            "Test Mode\n\n"
            "     Absolute basic launch\n"
            "     Only for testing if the server starts at all.")
        
        # Production mode card
        self._prod_card = QPushButton()
        self._prod_card.setCheckable(True)
        self._prod_card.setAutoExclusive(True)
        self._prod_card.setMinimumHeight(100)
        self._prod_card.setStyleSheet(self._card_style("#1e2e1e", "#45475a"))
        self._prod_card.setText(
            "Production Mode\n\n"
            "     Uses optimized performance settings\n"
            "     For making the server public")

        # Add to group and layout
        self._launch_group.addButton(self._test_card)
        self._launch_group.addButton(self._prod_card)
        
        lay.addWidget(self._test_card)
        lay.addWidget(self._prod_card)

        # Connect signals
        self._test_card.clicked.connect(lambda: self._select_launch_mode("test"))
        self._prod_card.clicked.connect(lambda: self._select_launch_mode("production"))

        # Set default state
        self._launch_mode = "test"
        self._test_card.setChecked(True)

        lay.addStretch(); return page

    def _select_launch_mode(self, mode: str):
        self._launch_mode = mode
        self._test_card.setChecked(mode == "test")
        self._prod_card.setChecked(mode == "production")
        self._continue_btn.setEnabled(True)

    # ══════════════════════════════════════════════════════════════
    #  PAGE 10 — Existing server list
    # ══════════════════════════════════════════════════════════════

    def _build_page_existing(self):
        page, lay = self._content_page()
        lay.addWidget(_h2("Choose a saved server"))
        lay.addWidget(_caption("Servers you've previously set up with MCServerMaker."))
        lay.addWidget(_divider())
        self._saved_servers_layout = QVBoxLayout(); self._saved_servers_layout.setSpacing(8)
        lay.addLayout(self._saved_servers_layout)
        self._no_servers_label = QLabel("No saved servers found.\nUse 'New Server' to set one up first.")
        self._no_servers_label.setStyleSheet("color:#6c7086;font-size:13px;")
        self._no_servers_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._no_servers_label)
        lay.addStretch()
        self._selected_existing: Optional[dict] = None; return page

    def _refresh_saved_servers(self):
        while self._saved_servers_layout.count():
            item = self._saved_servers_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        servers = load_saved_servers()
        self._no_servers_label.setVisible(len(servers) == 0)
        self._continue_btn.setEnabled(False)
        self._existing_btn_group = QButtonGroup(self); self._existing_btn_group.setExclusive(True)
        for i, srv in enumerate(servers):
            btn = QPushButton(); btn.setCheckable(True); btn.setMinimumHeight(64)
            btn.setStyleSheet("""
                QPushButton{background:#313244;border:2px solid #45475a;
                    border-radius:10px;color:#cdd6f4;
                    text-align:left;padding:10px 16px;font-size:13px;}
                QPushButton:hover{border-color:#89b4fa;}
                QPushButton:checked{border-color:#89b4fa;background:#1e3a5f;
                    color:#89b4fa;font-weight:bold;}
            """)
            btn.setText(f"🖥️  {srv.get('name','Unnamed')}\n      {srv.get('directory','')}")
            btn.clicked.connect(lambda _, s=srv: self._on_existing_selected(s))
            self._existing_btn_group.addButton(btn, i)
            self._saved_servers_layout.addWidget(btn)

    def _on_existing_selected(self, srv):
        self._selected_existing = srv; self._continue_btn.setEnabled(True)

    def _validate_existing(self):
        if not self._selected_existing:
            self._err_label.setText("Please select a server!"); return
        srv = self._selected_existing
        self.config.server_directory = srv.get("directory","")
        self.config.server_jar_path  = srv.get("jar","")
        self.config.java_path        = srv.get("java", self._java_path or "java")
        self._show_page(PAGE_LAUNCH)

    # ══════════════════════════════════════════════════════════════
    #  FINISH
    # ══════════════════════════════════════════════════════════════

    def _finish(self):
        self.config.java_path = self._java_path or "java"
        if self._flow == "new":
            self.config.ram_min_mb = self._min_slider.value()
            self.config.ram_max_mb = self._max_slider.value()
            save_server_to_list(
                os.path.basename(self.config.server_directory) or "My Server",
                self.config)
        save_config(self.config)
        self.config._use_aikars = (self._launch_mode == "production")
        from ui.dashboard_window import DashboardWindow
        self._dashboard = DashboardWindow(self.config)
        self._dashboard.show()
        self.close()
