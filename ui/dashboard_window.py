"""
ui/dashboard_window.py — Control Room Dashboard

Left panel tabs:
  🖥  Control   — Start / Stop / Restart / Kill + state badge
  📊  Monitor   — CPU, RAM, uptime
  🌍  World     — Players, broadcast, save, backup, game shortcuts
  ⚙️  Properties — server.properties: Form view + Raw editor tabs
  ❓  Help      — Tutorials for port-forwarding, joining, etc.

Right panel: interactive console + command input.

Responsive design:
  - QSplitter lets user resize left/right freely
  - All widgets use size policies so they grow/shrink gracefully
  - No fixed widths except the minimum sidebar
  - Scroll areas on every tall tab so nothing clips
"""

import os
import datetime
import socket

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QPlainTextEdit, QTextEdit, QLineEdit, QFrame,
    QProgressBar, QTabWidget, QSizePolicy, QScrollArea, QFormLayout,
    QCheckBox, QSpinBox, QComboBox, QButtonGroup, QGroupBox,
)

from core.config import ServerConfig
from core.server_manager import ServerManager


# ── Style helpers ──────────────────────────────────────────────────

TAB_STYLE = """
    QTabWidget::pane{border:none;background:#181825;}
    QTabBar::tab{
        background:#1e1e2e;color:#6c7086;
        padding:8px 10px;font-size:12px;
        border:none;border-bottom:2px solid transparent;
    }
    QTabBar::tab:selected{color:#89b4fa;border-bottom:2px solid #89b4fa;}
    QTabBar::tab:hover{color:#cdd6f4;}
"""

INNER_TAB_STYLE = """
    QTabWidget::pane{border:1px solid #313244;background:#1e1e2e;border-radius:6px;}
    QTabBar::tab{
        background:#181825;color:#6c7086;
        padding:6px 14px;font-size:11px;
        border:none;border-bottom:2px solid transparent;
    }
    QTabBar::tab:selected{color:#89b4fa;border-bottom:2px solid #89b4fa;}
    QTabBar::tab:hover{color:#cdd6f4;}
"""

SCROLL_STYLE = "QScrollArea{border:none;background:transparent;}"

def _bold(text, color="#cdd6f4", size=13):
    l = QLabel(text)
    l.setStyleSheet(f"font-size:{size}px;font-weight:bold;color:{color};")
    return l

def _caption(text):
    l = QLabel(text); l.setWordWrap(True)
    l.setStyleSheet("color:#6c7086;font-size:11px;"); return l

def _divider():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#313244;margin:4px 0;"); return f

def _btn(label, color="#313244", text_color="#cdd6f4",
         border="#45475a", hover="#45475a"):
    b = QPushButton(label); b.setMinimumHeight(36)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.setStyleSheet(f"""
        QPushButton{{background:{color};color:{text_color};border:1px solid {border};
            border-radius:7px;padding:4px 12px;font-size:13px;}}
        QPushButton:hover{{background:{hover};}}
        QPushButton:disabled{{background:#252535;color:#45475a;border-color:#313244;}}
    """); return b

def _scrollable(widget):
    """Wraps a widget in a QScrollArea for tall tab content."""
    s = QScrollArea(); s.setWidget(widget); s.setWidgetResizable(True)
    s.setStyleSheet(SCROLL_STYLE); s.setFrameShape(QFrame.Shape.NoFrame)
    return s


# ── server.properties field definitions ───────────────────────────
# (key, label, type, default, description, options_if_combo)
PROPS_FIELDS = [
    # Gameplay
    ("gamemode",          "Game Mode",         "combo",    "survival",
     "Default gamemode for new players.",
     ["survival","creative","adventure","spectator"]),
    ("difficulty",        "Difficulty",        "combo",    "easy",
     "Server difficulty level.",
     ["peaceful","easy","normal","hard"]),
    ("max-players",       "Max Players",       "int",      "20",
     "Maximum number of players allowed.", None),
    ("pvp",               "PvP",               "bool",     "true",
     "Allow player vs player combat.", None),
    ("hardcore",          "Hardcore Mode",     "bool",     "false",
     "Players are banned on death.", None),
    ("allow-flight",      "Allow Flight",      "bool",     "false",
     "Allow flying in survival mode.", None),
    # World
    ("level-name",        "World Name",        "str",      "world",
     "Name of the world folder.", None),
    ("level-seed",        "World Seed",        "str",      "",
     "Seed used to generate the world.", None),
    ("level-type",        "Level Type",        "combo",    "minecraft:default",
     "World generation type.",
     ["minecraft:default","minecraft:flat","minecraft:large_biomes",
      "minecraft:amplified","minecraft:single_biome_surface"]),
    ("generate-structures","Generate Structures","bool",   "true",
     "Generate villages, dungeons, etc.", None),
    ("view-distance",     "View Distance",     "int",      "10",
     "Chunks sent to players (2–32). Lower = better performance.", None),
    ("simulation-distance","Simulation Distance","int",    "10",
     "Distance at which entities are ticked.", None),
    ("spawn-animals",     "Spawn Animals",     "bool",     "true",
     "Allow passive animal spawning.", None),
    ("spawn-monsters",    "Spawn Monsters",    "bool",     "true",
     "Allow hostile mob spawning.", None),
    ("spawn-npcs",        "Spawn NPCs",        "bool",     "true",
     "Allow villager spawning.", None),
    # Network
    ("server-port",       "Server Port",       "int",      "25565",
     "Port the server listens on (default 25565).", None),
    ("server-ip",         "Server IP",         "str",      "",
     "Bind IP address. Leave blank to use all interfaces.", None),
    ("online-mode",       "Online Mode",       "bool",     "true",
     "Verify players with Mojang. Disable for offline/LAN.", None),
    ("network-compression-threshold","Compression Threshold","int","256",
     "Packet size threshold for compression (-1 = off).", None),
    # Security & misc
    ("white-list",        "Whitelist",         "bool",     "false",
     "Only allow whitelisted players.", None),
    ("enforce-whitelist", "Enforce Whitelist", "bool",     "false",
     "Kick non-whitelisted players when whitelist is enabled.", None),
    ("op-permission-level","OP Permission Level","int",    "4",
     "Permission level granted to operators (1–4).", None),
    ("enable-command-block","Command Blocks",  "bool",     "false",
     "Allow command blocks in the world.", None),
    ("motd",              "MOTD",              "str",      "A Minecraft Server",
     "Message shown in the server list.", None),
    ("max-world-size",    "Max World Size",    "int",      "29999984",
     "Maximum radius of the world border.", None),
]

# ── Help articles ──────────────────────────────────────────────────
HELP_ARTICLES = [
    ("Port Forwarding (bad)", """
<b>How to let other players join your server</b><br><br>

By default your server is only accessible on your local network.
To let friends join from the internet you need to forward port <b>25565</b> on your router.<br><br>

<b>Step 1 — Find your local IP</b><br>
Open a terminal and run:<br>
<code>  ip addr show | grep "inet " | grep -v 127.0.0.1</code><br>
Your local IP looks like <code>192.168.x.x</code><br><br>

<b>Step 2 — Log into your router</b><br>
Open a browser and go to <code>192.168.1.1</code> or <code>192.168.0.1</code>.
Log in (check the label on your router for credentials).<br><br>

<b>Step 3 — Add a port forwarding rule</b><br>
Look for "Port Forwarding", "NAT", or "Virtual Servers".<br>
Add a rule:<br>
&nbsp;&nbsp;• Protocol: <b>TCP</b><br>
&nbsp;&nbsp;• External port: <b>25565</b><br>
&nbsp;&nbsp;• Internal port: <b>25565</b><br>
&nbsp;&nbsp;• Internal IP: <i>your local IP from Step 1</i><br><br>

<b>Step 4 — Find your public IP</b><br>
Visit <a href="https://whatismyip.com" style="color:#89b4fa;">whatismyip.com</a>
and share that address with your friends.<br><br>

<b>Step 5 — Friends connect with:</b><br>
<code>  your.public.ip:25565</code><br><br>

<b>Firewall tip</b><br>
Make sure port 25565 is allowed through your Linux firewall:<br>
<code>  sudo ufw allow 25565/tcp</code>
"""),

    ("Local Network Play (Same WiFi)", """
<b>Playing with people on the same network</b><br><br>

This is the easiest setup — no port forwarding needed.<br><br>

<b>Step 1 — Find your local IP</b><br>
<code>  ip addr show | grep "inet " | grep -v 127.0.0.1</code><br>
e.g. <code>192.168.1.42</code><br><br>

<b>Step 2 — Make sure online-mode is set correctly</b><br>
In the Properties tab, set <b>Online Mode = false</b> if anyone
doesn't have a paid Minecraft account.<br><br>

<b>Step 3 — Friends connect with:</b><br>
<code>  192.168.1.42:25565</code>  (use your actual local IP)<br><br>

<b>Tip:</b> You can also use your hostname:<br>
<code>  hostname -I</code> — shows all local IPs
"""),

    ("Free Tunneling with Playit.gg (good option)", """
<b>No port forwarding? Use a free tunnel.</b><br><br>

<a href="https://playit.gg" style="color:#89b4fa;">playit.gg</a> gives you
a free public address that tunnels to your server — no router access needed.<br><br>

<b>Step 1 — Download the agent</b><br>
<code>  curl -SsL https://playit-cloud.github.io/ppa/key.gpg | sudo apt-key add -</code><br>
<code>  sudo apt install playit</code><br><br>

<b>Step 2 — Run the agent</b><br>
<code>  playit</code><br>
Follow the link it prints to claim your tunnel.<br><br>

<b>Step 3 — Select "Minecraft Java" as tunnel type</b><br>
You'll get an address like <code>auto.playit.gg:12345</code><br><br>

<b>Step 4 — Share that address with friends</b><br>
They connect to it exactly like a normal server address.
"""),

    ("Making Someone an OP (Admin)", """
<b>How to give a player operator permissions</b><br><br>

OPs can use all commands, change game settings, and manage the server.<br><br>

<b>From the console (server running):</b><br>
Type in the console input box at the bottom:<br>
<code>  op PlayerName</code><br><br>

<b>To remove OP:</b><br>
<code>  deop PlayerName</code><br><br>

<b>OP permission levels (set in Properties tab):</b><br>
&nbsp;&nbsp;• <b>1</b> — Bypass spawn protection only<br>
&nbsp;&nbsp;• <b>2</b> — Use most commands (default)<br>
&nbsp;&nbsp;• <b>3</b> — Manage players, kick/ban<br>
&nbsp;&nbsp;• <b>4</b> — All permissions including server management<br><br>

<b>Whitelist a player:</b><br>
<code>  whitelist add PlayerName</code><br>
<code>  whitelist on</code>  ← enable whitelist
"""),

    ("Banning and Kicking Players", """
<b>Managing problem players</b><br><br>

<b>Kick a player (temporary):</b><br>
<code>  kick PlayerName Reason here</code><br><br>

<b>Ban a player (permanent):</b><br>
<code>  ban PlayerName Reason here</code><br><br>

<b>Ban by IP address:</b><br>
<code>  ban-ip 1.2.3.4</code><br><br>

<b>Pardon (unban) a player:</b><br>
<code>  pardon PlayerName</code><br><br>

<b>View ban list:</b><br>
<code>  banlist</code><br><br>

<b>All bans are stored in:</b><br>
<code>  banned-players.json</code><br>
<code>  banned-ips.json</code><br>
in your server folder.
"""),

    ("Backups & World Management", """
<b>How to back up your world</b><br><br>

<b>Manual backup (from the World tab):</b><br>
1. Click <b>Backup World</b> — this runs <code>save-off</code> then <code>save-all</code><br>
2. Copy your world folder somewhere safe:<br>
<code>  cp -r /your/server/world ~/backups/world_$(date +%Y%m%d)</code><br>
3. Click <b>Save World</b> to re-enable auto-saves<br><br>

<b>Automated backup script:</b><br>
<code>  #!/bin/bash</code><br>
<code>  SRC=/your/server/world</code><br>
<code>  DST=~/backups/world_$(date +%Y%m%d_%H%M)</code><br>
<code>  cp -r "$SRC" "$DST"</code><br>
<code>  echo "Backed up to $DST"</code><br><br>

<b>Schedule with cron:</b><br>
<code>  crontab -e</code><br>
Add: <code>0 3 * * * /path/to/backup.sh</code>  ← runs at 3am daily
"""),

    ("Performance Tips", """
<b>Getting the best performance from your server</b><br><br>

<b>Use Production Mode (Aikar's flags)</b><br>
Selected at launch — optimizes Java garbage collection
for Minecraft's memory patterns. Biggest single improvement.<br><br>

<b>Reduce view distance</b><br>
In Properties → View Distance. Set to 6-8 for better TPS.
Default of 10 is fine for ≤10 players.<br><br>

<b>Check TPS (ticks per second)</b><br>
Healthy server = 20 TPS. Type in console:<br>
<code>  /tps</code>  (requires a plugin like Paper)<br><br>

<b>RAM recommendation:</b><br>
&nbsp;&nbsp;• 1-5 players: 2 GB<br>
&nbsp;&nbsp;• 5-15 players: 4 GB<br>
&nbsp;&nbsp;• 15-30 players: 6-8 GB<br><br>

<b>Consider Paper/Purpur</b><br>
Drop-in replacements for vanilla that are significantly faster.
Download from <a href="https://papermc.io" style="color:#89b4fa;">papermc.io</a>
"""),
]


# ══════════════════════════════════════════════════════════════════
#  Dashboard Window
# ══════════════════════════════════════════════════════════════════

class DashboardWindow(QMainWindow):
    def __init__(self, config: ServerConfig):
        super().__init__()
        self.config  = config
        self.manager = ServerManager(self)
        self.setWindowTitle("MCServerMaker | Dashboard")
        self.setMinimumSize(800, 500)
        self.resize(1140, 700)

        self._last_cpu = -1.0
        self._last_ram = -1
        self._pending_restart = False
        self._server_uptime_secs = 0
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        # server.properties in-memory dict
        self._props: dict[str, str] = {}

        self._build_ui()
        self._connect_signals()
        self._set_server_state("stopped")
        self._start_server()

    # ══════════════════════════════════════════════════════════════
    #  UI BUILD
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_status_bar())

        # Main splitter — resizable left/right
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(3)
        self._splitter.setStyleSheet(
            "QSplitter::handle{background:#313244;}"
            "QSplitter::handle:hover{background:#89b4fa;}")
        self._splitter.setChildrenCollapsible(False)
        root.addWidget(self._splitter, stretch=1)

        self._splitter.addWidget(self._build_left_panel())
        self._splitter.addWidget(self._build_right_panel())
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([280, 860])

    # ── Status bar ─────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = QWidget()
        bar.setStyleSheet("background:#181825;")
        bar.setFixedHeight(42)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 16, 0)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color:#f9e2af;font-size:18px;")
        row.addWidget(self._status_dot)

        self._status_label = QLabel("Starting…")
        self._status_label.setStyleSheet("font-weight:bold;font-size:13px;")
        row.addWidget(self._status_label)

        self._uptime_label = QLabel("")
        self._uptime_label.setStyleSheet("color:#6c7086;font-size:12px;margin-left:8px;")
        row.addWidget(self._uptime_label)

        row.addStretch()

        self._mode_label = QLabel(
            "Production Mode" if getattr(self.config, "_use_aikars", False)
            else "Test Mode")
        self._mode_label.setStyleSheet("color:#6c7086;font-size:12px;")
        row.addWidget(QLabel(f"jar: {os.path.basename(self.config.server_jar_path)}"))
        row.addSpacing(16)
        row.addWidget(QLabel(f"Allocated RAM: {self.config.ram_min_mb}–{self.config.ram_max_mb} MB"))
        row.addSpacing(16)
        row.addWidget(self._mode_label)
        row.addSpacing(16)

        props_btn = QPushButton("server.properties")
        props_btn.setStyleSheet("""
            QPushButton{background:#313244;color:#cdd6f4;border:1px solid #45475a;
                border-radius:6px;padding:3px 12px;font-size:12px;}
            QPushButton:hover{background:#45475a;}
        """)
        props_btn.setFixedHeight(28)
        props_btn.clicked.connect(self._open_properties_window)
        row.addWidget(props_btn)
        row.addSpacing(6)

        help_btn = QPushButton("Help")
        help_btn.setStyleSheet("""
            QPushButton{background:#1e3a5f;color:#89b4fa;border:1px solid #89b4fa;
                border-radius:6px;padding:3px 12px;font-size:12px;}
            QPushButton:hover{background:#24497a;}
        """)
        help_btn.setFixedHeight(28)
        help_btn.clicked.connect(self._open_help_window)
        row.addWidget(help_btn)
        row.addSpacing(8)

        return bar

    # ── Left panel ─────────────────────────────────────────────────

    def _build_left_panel(self):
        wrap = QWidget()
        wrap.setMinimumWidth(220)
        wrap.setStyleSheet("background:#181825;")
        wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.setStyleSheet(TAB_STYLE)
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tabs.addTab(self._build_control_tab(),    "🖥")
        tabs.addTab(self._build_monitor_tab(),    "📊")
        tabs.addTab(self._build_world_tab(),      "🌍")
        tabs.setTabToolTip(0, "Server Control")
        tabs.setTabToolTip(1, "Resource Monitor")
        tabs.setTabToolTip(2, "World & Players")
        wl.addWidget(tabs)
        return wrap

    def _open_properties_window(self):
        if hasattr(self, "_props_win") and self._props_win.isVisible():
            self._props_win.raise_(); self._props_win.activateWindow();
            return
        self._props_win = PropertiesWindow(self.config, self)
        self._props_win.show()

    def _open_help_window(self):
        if hasattr(self, "_help_win") and self._help_win.isVisible():
            self._help_win.raise_(); self._help_win.activateWindow();
            return
        self._help_win = HelpWindow(self)
        self._help_win.show()

    # ── TAB: Control ───────────────────────────────────────────────

    def _build_control_tab(self):
        inner = QWidget(); inner.setStyleSheet("background:#181825;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 14, 12, 14); lay.setSpacing(10)

        self._state_badge = QLabel("● STOPPED")
        self._state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_badge.setStyleSheet(
            "background:#2a1a1a;color:#f38ba8;font-weight:bold;"
            "font-size:13px;border-radius:8px;padding:8px;")
        self._state_badge.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._state_badge)
        lay.addWidget(_divider())

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._start_test_btn = QPushButton("Start Test")
        self._start_test_btn.setCheckable(True)
        self._start_test_btn.setStyleSheet("""
            QPushButton{background:#1e3a1e;color:#a6e3a1;border:1px solid #a6e3a1;
                border-radius:7px;padding:8px 12px;font-size:13px;}
            QPushButton:hover{background:#243824;}
            QPushButton:checked{background:#89b4fa;color:#1e1e2e;}
        """)
        self._start_test_btn.setMinimumHeight(42)

        self._start_prod_btn = QPushButton("Start Production")
        self._start_prod_btn.setCheckable(True)
        self._start_prod_btn.setStyleSheet("""
            QPushButton{background:#1e3a1e;color:#a6e3a1;border:1px solid #a6e3a1;
                border-radius:7px;padding:8px 12px;font-size:13px;}
            QPushButton:hover{background:#243824;}
            QPushButton:checked{background:#89b4fa;color:#1e1e2e;}
        """)
        self._start_prod_btn.setMinimumHeight(42)

        self._mode_group.addButton(self._start_test_btn)
        self._mode_group.addButton(self._start_prod_btn)

        self._start_test_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._start_prod_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mode_row = QHBoxLayout(); mode_row.setSpacing(10)
        mode_row.addWidget(self._start_test_btn)
        mode_row.addWidget(self._start_prod_btn)
        lay.addLayout(mode_row)

        self._stop_btn  = _btn("⏹  Stop",    "#3a1e1e","#f38ba8","#f38ba8","#4a2525")
        self._restart_btn = _btn("🔄  Restart","#1e2e3a","#89b4fa","#89b4fa","#1e3a5f")

        for b in (self._stop_btn, self._restart_btn):
            b.setMinimumHeight(42); lay.addWidget(b)

        self._start_test_btn.clicked.connect(lambda: self._cmd_start(False))
        self._start_prod_btn.clicked.connect(lambda: self._cmd_start(True))
        self._stop_btn.clicked.connect(self._cmd_stop)
        self._restart_btn.clicked.connect(self._cmd_restart)

        self._select_start_mode(getattr(self.config, "_use_aikars", False))

        lay.addWidget(_divider())
        self._kill_btn = _btn("☠️  Force Kill","#2a1a2a","#cba6f7","#cba6f7","#3a1a3a")
        self._kill_btn.clicked.connect(self._cmd_kill)
        lay.addWidget(self._kill_btn)
        lay.addWidget(_caption("Immediately terminates without saving."))

        lay.addStretch()
        lay.addWidget(_divider())
        self._info_dir = QLabel(f"📁 {os.path.basename(self.config.server_directory)}")
        self._info_dir.setStyleSheet("color:#6c7086;font-size:11px;")
        self._info_dir.setWordWrap(True)
        lay.addWidget(self._info_dir)
        return _scrollable(inner)

    # ── TAB: Monitor ───────────────────────────────────────────────

    def _build_monitor_tab(self):
        inner = QWidget(); inner.setStyleSheet("background:#181825;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 14, 12, 14); lay.setSpacing(10)

        lay.addWidget(_bold("CPU", "#cdd6f4", 12))
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0,100); self._cpu_bar.setValue(0)
        self._cpu_bar.setTextVisible(False); self._cpu_bar.setFixedHeight(16)
        self._cpu_bar.setStyleSheet(
            "QProgressBar{background:#313244;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#89b4fa;border-radius:3px;}")
        lay.addWidget(self._cpu_bar)
        self._cpu_label = QLabel("0.0%")
        self._cpu_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._cpu_label.setStyleSheet("color:#89b4fa;font-size:12px;")
        lay.addWidget(self._cpu_label)

        lay.addWidget(_bold("RAM", "#cdd6f4", 12))
        self._ram_bar = QProgressBar()
        self._ram_bar.setRange(0, max(self.config.ram_max_mb, 1))
        self._ram_bar.setValue(0); self._ram_bar.setTextVisible(False)
        self._ram_bar.setFixedHeight(16)
        self._ram_bar.setStyleSheet(
            "QProgressBar{background:#313244;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#a6e3a1;border-radius:3px;}")
        lay.addWidget(self._ram_bar)
        self._ram_label = QLabel(f"0 / {self.config.ram_max_mb} MB")
        self._ram_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._ram_label.setStyleSheet("color:#a6e3a1;font-size:12px;")
        lay.addWidget(self._ram_label)

        lay.addWidget(_divider())
        lay.addWidget(_bold("Uptime", "#cdd6f4", 12))
        self._uptime_big = QLabel("00:00:00")
        self._uptime_big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._uptime_big.setStyleSheet(
            "font-size:22px;font-weight:bold;color:#cba6f7;"
            "font-family:monospace;letter-spacing:2px;")
        self._uptime_big.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._uptime_big)
        lay.addStretch()
        return _scrollable(inner)

    # ── TAB: World ─────────────────────────────────────────────────

    def _build_world_tab(self):
        inner = QWidget(); inner.setStyleSheet("background:#181825;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 14, 12, 14); lay.setSpacing(8)

        lay.addWidget(_bold("Players", "#cdd6f4", 12))
        b = _btn("List Players"); b.clicked.connect(
            lambda: self.manager.send_command("list"))
        lay.addWidget(b)

        lay.addWidget(_bold("Broadcast", "#cdd6f4", 12))
        self._broadcast_input = QLineEdit()
        self._broadcast_input.setPlaceholderText("Message to all players…")
        self._broadcast_input.returnPressed.connect(self._cmd_broadcast)
        lay.addWidget(self._broadcast_input)
        bb = _btn("Send","#2e1e3a","#cba6f7","#cba6f7","#3a1e4a")
        bb.clicked.connect(self._cmd_broadcast); lay.addWidget(bb)

        lay.addWidget(_divider())
        lay.addWidget(_bold("World", "#cdd6f4", 12))
        for label, slot in [
            ("Save World",  lambda: self.manager.send_command("save-all")),
            ("Backup",      self._cmd_backup),
        ]:
            b = _btn(label); b.clicked.connect(slot); lay.addWidget(b)

        lay.addWidget(_divider())
        lay.addWidget(_bold("Quick Commands", "#cdd6f4", 12))
        for label, cmd in [
            ("Set Day",        "time set day"),
            ("Set Night",      "time set night"),
            ("Clear Weather",  "weather clear"),
            ("Set Rain",       "weather rain"),
            ("Set Thunder",    "weather thunder"),
        ]:
            b = _btn(label)
            b.clicked.connect(lambda _, c=cmd: self.manager.send_command(c))
            lay.addWidget(b)

        lay.addStretch()
        return _scrollable(inner)

    # ── TAB: Properties ────────────────────────────────────────────

    def _build_properties_tab(self):
        wrap = QWidget(); wrap.setStyleSheet("background:#181825;")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        inner_tabs = QTabWidget()
        inner_tabs.setStyleSheet(INNER_TAB_STYLE)
        inner_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ── Form view ──
        form_outer = QWidget(); form_outer.setStyleSheet("background:#1e1e2e;")
        form_lay = QVBoxLayout(form_outer)
        form_lay.setContentsMargins(10, 10, 10, 10); form_lay.setSpacing(8)

        self._prop_widgets: dict[str, QWidget] = {}

        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            group = QGroupBox(label)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            group.setStyleSheet("""
                QGroupBox{border:1px solid #313244;border-radius:6px;
                    margin-top:6px;padding:8px 8px 6px 8px;color:#89b4fa;font-size:12px;}
                QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}
            """)
            gl = QVBoxLayout(group); gl.setSpacing(4)

            if ftype == "bool":
                w = QCheckBox("Enabled")
                w.setChecked(default == "true")
                w.setStyleSheet("color:#cdd6f4;font-size:12px;")
            elif ftype == "int":
                w = QSpinBox()
                w.setRange(-1, 99999999)
                try: w.setValue(int(default))
                except: w.setValue(0)
                w.setStyleSheet(
                    "QSpinBox{background:#181825;color:#cdd6f4;border:1px solid #45475a;"
                    "border-radius:4px;padding:3px 6px;}"
                    "QSpinBox::up-button,QSpinBox::down-button{width:16px;}")
            elif ftype == "combo":
                w = QComboBox()
                w.addItems(options or [])
                idx = options.index(default) if options and default in options else 0
                w.setCurrentIndex(idx)
                w.setStyleSheet(
                    "QComboBox{background:#181825;color:#cdd6f4;border:1px solid #45475a;"
                    "border-radius:4px;padding:3px 8px;}"
                    "QComboBox::drop-down{border:none;width:20px;}"
                    "QComboBox QAbstractItemView{background:#181825;color:#cdd6f4;"
                    "selection-background-color:#313244;}")
            else:  # str
                w = QLineEdit(default)
                w.setStyleSheet(
                    "QLineEdit{background:#181825;color:#cdd6f4;border:1px solid #45475a;"
                    "border-radius:4px;padding:3px 6px;font-size:12px;}")

            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._prop_widgets[key] = w
            gl.addWidget(w)

            desc_lbl = QLabel(desc); desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color:#6c7086;font-size:11px;")
            gl.addWidget(desc_lbl)
            form_lay.addWidget(group)

        form_lay.addStretch()

        save_btn = _btn("Save server.properties",
                        "#1e3a5f","#89b4fa","#89b4fa","#24497a")
        save_btn.setMinimumHeight(40); save_btn.clicked.connect(self._save_properties_form)
        form_lay.addWidget(save_btn)

        inner_tabs.addTab(_scrollable(form_outer), "Form")

        # ── Raw editor ──
        raw_outer = QWidget(); raw_outer.setStyleSheet("background:#1e1e2e;")
        raw_lay = QVBoxLayout(raw_outer)
        raw_lay.setContentsMargins(8, 8, 8, 8); raw_lay.setSpacing(6)

        self._raw_editor = QPlainTextEdit()
        self._raw_editor.setFont(QFont("Monospace", 10))
        self._raw_editor.setStyleSheet(
            "background:#0d0d1a;color:#cdd6f4;border:1px solid #313244;border-radius:4px;")
        self._raw_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        raw_lay.addWidget(self._raw_editor)

        raw_btn_row = QHBoxLayout()
        reload_btn = _btn("🔄  Reload from file")
        reload_btn.clicked.connect(self._load_properties)
        raw_btn_row.addWidget(reload_btn)
        save_raw_btn = _btn("💾  Save","#1e3a5f","#89b4fa","#89b4fa","#24497a")
        save_raw_btn.clicked.connect(self._save_properties_raw)
        raw_btn_row.addWidget(save_raw_btn)
        raw_lay.addLayout(raw_btn_row)

        inner_tabs.addTab(raw_outer, "📝  Raw")

        # Load properties when tab is first shown
        inner_tabs.currentChanged.connect(
            lambda i: self._load_properties() if i == 0 else None)
        lay.addWidget(inner_tabs)

        # Load immediately
        self._load_properties()
        return wrap

    def _get_props_path(self):
        return os.path.join(self.config.server_directory, "server.properties")

    def _load_properties(self):
        path = self._get_props_path()
        if not os.path.isfile(path): return
        self._props = {}
        lines = []
        with open(path) as f:
            for line in f:
                lines.append(line)
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _, v = stripped.partition("=")
                    self._props[k.strip()] = v.strip()

        # Populate raw editor
        self._raw_editor.setPlainText("".join(lines))

        # Populate form widgets
        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            if key not in self._prop_widgets: continue
            val = self._props.get(key, default)
            w = self._prop_widgets[key]
            if ftype == "bool":
                w.setChecked(val.lower() == "true")
            elif ftype == "int":
                try: w.setValue(int(val))
                except: pass
            elif ftype == "combo":
                idx = options.index(val) if options and val in options else 0
                w.setCurrentIndex(idx)
            else:
                w.setText(val)

    def _save_properties_form(self):
        """Read form widgets → write server.properties."""
        path = self._get_props_path()
        if not os.path.isfile(path): return

        # Build dict of new values from form
        new_vals = {}
        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            if key not in self._prop_widgets: continue
            w = self._prop_widgets[key]
            if ftype == "bool":
                new_vals[key] = "true" if w.isChecked() else "false"
            elif ftype == "int":
                new_vals[key] = str(w.value())
            elif ftype == "combo":
                new_vals[key] = w.currentText()
            else:
                new_vals[key] = w.text()

        # Rewrite file preserving comments and key order
        with open(path) as f: lines = f.readlines()
        written_keys = set()
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                k = k.strip()
                if k in new_vals:
                    out.append(f"{k}={new_vals[k]}\n")
                    written_keys.add(k)
                else:
                    out.append(line)
            else:
                out.append(line)
        # Append any new keys not already in file
        for k, v in new_vals.items():
            if k not in written_keys:
                out.append(f"{k}={v}\n")

        with open(path, "w") as f: f.writelines(out)
        self._raw_editor.setPlainText("".join(out))

    def _save_properties_raw(self):
        """Write raw editor content directly to server.properties."""
        path = self._get_props_path()
        with open(path, "w") as f:
            f.write(self._raw_editor.toPlainText())
        self._load_properties()  # Sync form from newly saved file

    # ── TAB: Help ──────────────────────────────────────────────────

    def _build_help_tab(self):
        wrap = QWidget(); wrap.setStyleSheet("background:#181825;")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        help_tabs = QTabWidget()
        help_tabs.setStyleSheet(INNER_TAB_STYLE)
        help_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_tabs.setTabPosition(QTabWidget.TabPosition.West)
        help_tabs.setStyleSheet(INNER_TAB_STYLE + """
            QTabBar::tab{padding:10px 8px;font-size:11px;min-width:20px;}
        """)

        for title, html in HELP_ARTICLES:
            article = QWidget(); article.setStyleSheet("background:#1e1e2e;")
            al = QVBoxLayout(article)
            al.setContentsMargins(14, 14, 14, 14); al.setSpacing(0)

            view = QTextEdit()
            view.setReadOnly(True)
            view.setHtml(f"""
                <style>
                  body{{background:#1e1e2e;color:#cdd6f4;
                    font-family:'Noto Sans',sans-serif;font-size:13px;
                    line-height:1.6;}}
                  code{{background:#181825;color:#a6e3a1;padding:1px 5px;
                    border-radius:3px;font-family:monospace;font-size:12px;}}
                  b{{color:#89b4fa;}}
                  a{{color:#89b4fa;}}
                </style>
                <body>{html}</body>
            """)
            view.setStyleSheet(
                "QTextEdit{background:#1e1e2e;border:none;color:#cdd6f4;}")
            view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            al.addWidget(view)
            help_tabs.addTab(article, title.split("  ")[0])  # emoji only for tab
            help_tabs.setTabToolTip(help_tabs.count()-1, title)

        lay.addWidget(help_tabs)
        return wrap

    # ── Right panel: console ───────────────────────────────────────

    def _build_right_panel(self):
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 10, 10, 10); rl.setSpacing(8)
        rl.addWidget(_bold("🖥️  Server Console", "#89b4fa", 13))

        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setMaximumBlockCount(2000)
        mono = QFont("Monospace", 10)
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._console.setFont(mono)
        self._console.setStyleSheet(
            "background:#0d0d1a;color:#cdd6f4;"
            "border:1px solid #313244;border-radius:4px;")
        self._console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._console.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl.addWidget(self._console, stretch=1)

        input_row = QHBoxLayout()
        prompt = QLabel(">")
        prompt.setStyleSheet("color:#89b4fa;font-family:monospace;font-size:14px;")
        input_row.addWidget(prompt)
        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("Type a server command and press Enter…")
        self._cmd_input.setFont(mono)
        self._cmd_input.returnPressed.connect(self._send_command)
        input_row.addWidget(self._cmd_input)
        send_btn = QPushButton("Send")
        send_btn.setObjectName("primary")
        send_btn.clicked.connect(self._send_command)
        input_row.addWidget(send_btn)
        rl.addLayout(input_row)
        return right

    # ══════════════════════════════════════════════════════════════
    #  SIGNALS
    # ══════════════════════════════════════════════════════════════

    def _connect_signals(self):
        self.manager.output_line.connect(self._append_batch)
        self.manager.server_started.connect(self._on_server_started)
        self.manager.server_stopped.connect(self._on_server_stopped)
        self.manager.stats_updated.connect(self._on_stats_updated)

    # ══════════════════════════════════════════════════════════════
    #  SERVER STATE
    # ══════════════════════════════════════════════════════════════

    def _set_server_state(self, state: str):
        self._server_state = state
        is_running = (state == "running")
        is_stopped = (state == "stopped")

        colors = {"running":"#a6e3a1","stopped":"#f38ba8","starting":"#f9e2af"}
        self._status_dot.setStyleSheet(
            f"color:{colors.get(state,'#f9e2af')};font-size:18px;")
        self._status_label.setText(
            {"running":"Server running","stopped":"Server stopped",
             "starting":"Starting…"}.get(state, state))

        badges = {
            "running":  ("● RUNNING",  "#1a3a1a","#a6e3a1"),
            "stopped":  ("● STOPPED",  "#2a1a1a","#f38ba8"),
            "starting": ("● STARTING…","#2a2a1a","#f9e2af"),
        }
        txt, bg, fg = badges.get(state, ("●","#1e1e2e","#cdd6f4"))
        self._state_badge.setText(txt)
        self._state_badge.setStyleSheet(
            f"background:{bg};color:{fg};font-weight:bold;"
            f"font-size:13px;border-radius:8px;padding:8px;")

        self._start_test_btn.setEnabled(is_stopped)
        self._start_prod_btn.setEnabled(is_stopped)
        self._stop_btn.setEnabled(is_running)
        self._restart_btn.setEnabled(is_running)
        self._kill_btn.setEnabled(not is_stopped)

        if is_running:
            self._server_uptime_secs = 0; self._uptime_timer.start()
        else:
            self._uptime_timer.stop()
            if is_stopped:
                self._uptime_big.setText("00:00:00")
                self._uptime_label.setText("")

    def _select_start_mode(self, use_aikars: bool):
        self.config._use_aikars = use_aikars
        self._start_test_btn.setChecked(not use_aikars)
        self._start_prod_btn.setChecked(use_aikars)
        self._mode_label.setText(
            "Production Mode" if use_aikars else "Test Mode")

    def _tick_uptime(self):
        self._server_uptime_secs += 1
        s = self._server_uptime_secs
        h, r = divmod(s, 3600); m, sec = divmod(r, 60)
        txt = f"{h:02d}:{m:02d}:{sec:02d}"
        self._uptime_big.setText(txt)
        self._uptime_label.setText(f"up {txt}")

    def _start_server(self):
        self._set_server_state("starting")
        cmd = self.config.build_launch_command(
            use_aikars=getattr(self.config, "_use_aikars", False))
        self._append_system(f"[MCServerMaker] Launching: {' '.join(cmd)}", "#f9e2af")
        self.manager.start(cmd, self.config.server_directory)

    def _on_server_started(self):
        self._set_server_state("running")
        self._load_properties()

    def _on_server_stopped(self):
        self._set_server_state("stopped")
        self._append_system("[MCServerMaker] Server process exited.", "#f38ba8")
        self._cpu_bar.setValue(0); self._ram_bar.setValue(0)
        self._last_cpu = -1; self._last_ram = -1
        
        if self._pending_restart:
            self._pending_restart = False
            self._append_system("[MCServerMaker] Restarting (waiting for port to free)…", "#f9e2af")
            
            # Delay the start by 2 seconds (2000 ms) to avoid BindException
            QTimer.singleShot(2000, self._start_server)

    # ══════════════════════════════════════════════════════════════
    #  COMMANDS
    # ══════════════════════════════════════════════════════════════

    def _cmd_start(self, use_aikars: bool | None = None):
        if use_aikars is not None:
            self._select_start_mode(use_aikars)
        if not self.manager.is_running:
            self._start_server()

    def _cmd_stop(self):
        self._append_system("[MCServerMaker] Stopping…", "#f9e2af")
        self._set_server_state("starting")
        self.manager.stop()

    def _cmd_restart(self):
        self._pending_restart = True
        self._append_system("[MCServerMaker] Restarting…", "#f9e2af")
        self._set_server_state("starting")
        self.manager.stop()

    def _cmd_kill(self):
        self._append_system("[MCServerMaker] Force kill!", "#f38ba8")
        self.manager.kill()

    def _cmd_backup(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.manager.send_command("save-off")
        self.manager.send_command("save-all")
        self._append_system(
            f"[MCServerMaker] Backup triggered at {ts}. Run save-on when done.", "#f9e2af")

    def _cmd_broadcast(self):
        msg = self._broadcast_input.text().strip()
        if not msg: return
        self.manager.send_command(f"say {msg}")
        self._broadcast_input.clear()

    # ══════════════════════════════════════════════════════════════
    #  CONSOLE
    # ══════════════════════════════════════════════════════════════

    def _at_bottom(self):
        sb = self._console.verticalScrollBar()
        return sb.value() >= sb.maximum() - 4

    def _append_batch(self, text: str):
        at_bottom = self._at_bottom()
        self._console.appendPlainText(text)
        if at_bottom: self._console.ensureCursorVisible()

    def _append_system(self, line: str, color: str):
        at_bottom = self._at_bottom()
        safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        self._console.appendHtml(f'<span style="color:{color};">{safe}</span>')
        if at_bottom: self._console.ensureCursorVisible()

    def _send_command(self):
        text = self._cmd_input.text().strip()
        if not text: return
        self._append_system(f"> {text}", "#89b4fa")
        self.manager.send_command(text)
        self._cmd_input.clear()

    # ══════════════════════════════════════════════════════════════
    #  STATS
    # ══════════════════════════════════════════════════════════════

    def _on_stats_updated(self, cpu: float, ram_mb: float):
        cpu_int = int(cpu); ram_int = int(ram_mb)
        if cpu_int != self._last_cpu:
            self._last_cpu = cpu_int
            self._cpu_bar.setValue(cpu_int)
            self._cpu_label.setText(f"{cpu:.1f}%")
        if ram_int != self._last_ram:
            self._last_ram = ram_int
            self._ram_bar.setValue(min(ram_int, self.config.ram_max_mb))
            self._ram_label.setText(f"{ram_int} / {self.config.ram_max_mb} MB")

    # ══════════════════════════════════════════════════════════════
    #  CLOSE
    # ══════════════════════════════════════════════════════════════

    def closeEvent(self, event):
        self._uptime_timer.stop()
        if self.manager.is_running: self.manager.stop()
        event.accept()


# ══════════════════════════════════════════════════════════════════
#  Help Window
# ══════════════════════════════════════════════════════════════════

class HelpWindow(QMainWindow):
    """Standalone help & tutorials window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MCServerMaker — Help & Tutorials")
        self.setMinimumSize(720, 540)
        self.resize(980, 640)
        self.setStyleSheet("background:#1e1e2e;color:#cdd6f4;")
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        header.setStyleSheet("background:#181825;border-bottom:2px solid #89b4fa;")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("Help & Tutorials")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#89b4fa;")
        hl.addWidget(title)
        hl.addStretch()
        sub = QLabel("Click a topic on the left to read")
        sub.setStyleSheet("color:#6c7086;font-size:12px;")
        hl.addWidget(sub)
        lay.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(
            "QSplitter::handle{background:#313244;}"
            "QSplitter::handle:hover{background:#89b4fa;}")
        splitter.setChildrenCollapsible(False)
        lay.addWidget(splitter, stretch=1)

        topic_panel = QWidget()
        topic_panel.setStyleSheet("background:#181825;")
        topic_panel.setMinimumWidth(180)
        topic_panel.setMaximumWidth(260)
        tl = QVBoxLayout(topic_panel)
        tl.setContentsMargins(0, 8, 0, 8)
        tl.setSpacing(2)

        self._topic_btns: list[QPushButton] = []
        for i, (title_str, _) in enumerate(HELP_ARTICLES):
            btn = QPushButton(title_str)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton{background:transparent;color:#6c7086;border:none;
                    text-align:left;padding:10px 16px;font-size:12px;border-radius:0;}
                QPushButton:hover{background:#313244;color:#cdd6f4;}
                QPushButton:checked{background:#1e3a5f;color:#89b4fa;
                    font-weight:bold;border-left:3px solid #89b4fa;}
            """)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, idx=i: self._show_article(idx))
            self._topic_btns.append(btn)
            tl.addWidget(btn)
        tl.addStretch()
        splitter.addWidget(topic_panel)

        self._article_view = QTextEdit()
        self._article_view.setReadOnly(True)
        self._article_view.setStyleSheet(
            "QTextEdit{background:#1e1e2e;color:#cdd6f4;border:none;"
            "padding:20px;font-size:13px;}")
        self._article_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        splitter.addWidget(self._article_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 660])

        self._show_article(0)

    def _show_article(self, index: int):
        for i, btn in enumerate(self._topic_btns):
            btn.setChecked(i == index)
        _, html = HELP_ARTICLES[index]
        self._article_view.setHtml(f"""
            <style>
              body{{background:#1e1e2e;color:#cdd6f4;
                font-family:'Noto Sans',sans-serif;font-size:13px;line-height:1.7;
                padding:8px;}}
              code{{background:#181825;color:#a6e3a1;padding:2px 6px;
                border-radius:3px;font-family:monospace;font-size:12px;}}
              b{{color:#89b4fa;}}
              a{{color:#89b4fa;}}
            </style>
            <body>{html}</body>
        """)


# ══════════════════════════════════════════════════════════════════
#  Properties Window
# ══════════════════════════════════════════════════════════════════

class PropertiesWindow(QMainWindow):
    """Standalone server.properties editor window."""

    def __init__(self, config: ServerConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("MCServerMaker — server.properties")
        self.setMinimumSize(640, 500)
        self.resize(780, 660)
        self.setStyleSheet("background:#1e1e2e;color:#cdd6f4;")
        self._props: dict[str, str] = {}
        self._prop_widgets: dict[str, QWidget] = {}
        self._build_ui()
        self._load_properties()

    def _get_props_path(self):
        return os.path.join(self.config.server_directory, "server.properties")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        header.setStyleSheet("background:#181825;border-bottom:2px solid #89b4fa;")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("Server Properties editor")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#89b4fa;")
        hl.addWidget(title)
        hl.addStretch()
        path_lbl = QLabel(self._get_props_path())
        path_lbl.setStyleSheet("color:#6c7086;font-size:11px;")
        hl.addWidget(path_lbl)
        lay.addWidget(header)

        inner_tabs = QTabWidget()
        inner_tabs.setStyleSheet("""
            QTabWidget::pane{border:none;background:#1e1e2e;}
            QTabBar::tab{background:#181825;color:#6c7086;padding:10px 20px;
                font-size:13px;border:none;border-bottom:2px solid transparent;}
            QTabBar::tab:selected{color:#89b4fa;border-bottom:2px solid #89b4fa;}
            QTabBar::tab:hover{color:#cdd6f4;}
        """)
        inner_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(inner_tabs, stretch=1)

        form_outer = QWidget(); form_outer.setStyleSheet("background:#1e1e2e;")
        form_lay = QVBoxLayout(form_outer)
        form_lay.setContentsMargins(16, 16, 16, 12); form_lay.setSpacing(8)

        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            group = QGroupBox(label)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            group.setStyleSheet("""
                QGroupBox{border:1px solid #313244;border-radius:6px;
                    margin-top:6px;padding:8px 8px 6px 8px;
                    color:#89b4fa;font-size:12px;}
                QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}
            """)
            gl = QVBoxLayout(group); gl.setSpacing(4)

            if ftype == "bool":
                w = QCheckBox("Enabled")
                w.setChecked(default == "true")
                w.setStyleSheet("color:#cdd6f4;font-size:12px;")
            elif ftype == "int":
                w = QSpinBox()
                w.setRange(-1, 99999999)
                try: w.setValue(int(default))
                except: w.setValue(0)
                w.setStyleSheet(
                    "QSpinBox{background:#181825;color:#cdd6f4;"
                    "border:1px solid #45475a;border-radius:4px;padding:3px 6px;}"
                    "QSpinBox::up-button,QSpinBox::down-button{width:16px;}")
            elif ftype == "combo":
                w = QComboBox()
                w.addItems(options or [])
                idx = options.index(default) if options and default in options else 0
                w.setCurrentIndex(idx)
                w.setStyleSheet(
                    "QComboBox{background:#181825;color:#cdd6f4;"
                    "border:1px solid #45475a;border-radius:4px;padding:3px 8px;}"
                    "QComboBox::drop-down{border:none;width:20px;}"
                    "QComboBox QAbstractItemView{background:#181825;color:#cdd6f4;"
                    "selection-background-color:#313244;}")
            else:
                w = QLineEdit(default)
                w.setStyleSheet(
                    "QLineEdit{background:#181825;color:#cdd6f4;"
                    "border:1px solid #45475a;border-radius:4px;"
                    "padding:3px 6px;font-size:12px;}")

            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._prop_widgets[key] = w
            gl.addWidget(w)

            desc_lbl = QLabel(desc); desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color:#6c7086;font-size:11px;")
            gl.addWidget(desc_lbl)
            form_lay.addWidget(group)

        form_lay.addStretch()

        save_form_btn = QPushButton("Save Changes")
        save_form_btn.setMinimumHeight(42)
        save_form_btn.setStyleSheet("""
            QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #89b4fa,stop:1 #cba6f7);color:#1e1e2e;font-weight:bold;
                font-size:14px;border:none;border-radius:8px;}
            QPushButton:hover{background:#b4d0fb;}
        """)
        save_form_btn.clicked.connect(self._save_form)
        form_lay.addWidget(save_form_btn)

        scroll = QScrollArea(); scroll.setWidget(form_outer)
        scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{border:none;background:#1e1e2e;}")
        inner_tabs.addTab(scroll, "Easy View")

        raw_outer = QWidget(); raw_outer.setStyleSheet("background:#1e1e2e;")
        raw_lay = QVBoxLayout(raw_outer)
        raw_lay.setContentsMargins(12, 12, 12, 12); raw_lay.setSpacing(8)

        self._raw_editor = QPlainTextEdit()
        self._raw_editor.setFont(QFont("Monospace", 10))
        self._raw_editor.setStyleSheet(
            "background:#0d0d1a;color:#cdd6f4;"
            "border:1px solid #313244;border-radius:4px;padding:8px;")
        self._raw_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        raw_lay.addWidget(self._raw_editor)

        raw_btn_row = QHBoxLayout()
        reload_btn = QPushButton("Reload from file")
        reload_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:7px;padding:6px 14px;}"
            "QPushButton:hover{background:#45475a;}")
        reload_btn.clicked.connect(self._load_properties)
        raw_btn_row.addWidget(reload_btn)

        save_raw_btn = QPushButton("Save changes")
        save_raw_btn.setStyleSheet("""
            QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #89b4fa,stop:1 #cba6f7);color:#1e1e2e;font-weight:bold;
                border:none;border-radius:7px;padding:6px 20px;}
            QPushButton:hover{background:#b4d0fb;}
        """)
        save_raw_btn.clicked.connect(self._save_raw)
        raw_btn_row.addWidget(save_raw_btn)
        raw_lay.addLayout(raw_btn_row)
        inner_tabs.addTab(raw_outer, "RAW file (Complex warning!)")

    def _load_properties(self):
        path = self._get_props_path()
        if not os.path.isfile(path): return
        self._props = {}
        lines = []
        with open(path) as f:
            for line in f:
                lines.append(line)
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _, v = stripped.partition("=")
                    self._props[k.strip()] = v.strip()
        self._raw_editor.setPlainText("".join(lines))
        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            if key not in self._prop_widgets: continue
            val = self._props.get(key, default)
            w = self._prop_widgets[key]
            if ftype == "bool":
                w.setChecked(val.lower() == "true")
            elif ftype == "int":
                try: w.setValue(int(val))
                except: pass
            elif ftype == "combo":
                idx = options.index(val) if options and val in options else 0
                w.setCurrentIndex(idx)
            else:
                w.setText(val)

    def _save_form(self):
        path = self._get_props_path()
        if not os.path.isfile(path): return
        new_vals = {}
        for key, label, ftype, default, desc, options in PROPS_FIELDS:
            if key not in self._prop_widgets: continue
            w = self._prop_widgets[key]
            if ftype == "bool":   new_vals[key] = "true" if w.isChecked() else "false"
            elif ftype == "int":  new_vals[key] = str(w.value())
            elif ftype == "combo":new_vals[key] = w.currentText()
            else:                 new_vals[key] = w.text()
        with open(path) as f: lines = f.readlines()
        written = set(); out = []
        for line in lines:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k = s.partition("=")[0].strip()
                if k in new_vals:
                    out.append(f"{k}={new_vals[k]}\n"); written.add(k)
                else: out.append(line)
            else: out.append(line)
        for k, v in new_vals.items():
            if k not in written: out.append(f"{k}={v}\n")
        with open(path, "w") as f: f.writelines(out)
        self._raw_editor.setPlainText("".join(out))

    def _save_raw(self):
        path = self._get_props_path()
        with open(path, "w") as f:
            f.write(self._raw_editor.toPlainText())
        self._load_properties()
