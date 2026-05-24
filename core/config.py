"""
core/config.py
Handles loading and saving server configuration to:
  ~/.config/MCServerMaker/config.json
"""
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional


CONFIG_DIR = os.path.expanduser("~/.config/MCServerMaker")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class ServerConfig:
    # Paths
    server_jar_path: str = ""
    server_directory: str = ""
    java_path: str = "java"

    # Memory (in MB)
    ram_min_mb: int = 1024
    ram_max_mb: int = 2048

    # EULA
    eula_accepted: bool = False

    # Extra JVM flags (space-separated string)
    extra_jvm_flags: str = ""

    @property
    def xms_flag(self) -> str:
        return f"-Xms{self.ram_min_mb}M"

    @property
    def xmx_flag(self) -> str:
        return f"-Xmx{self.ram_max_mb}M"

    def build_launch_command(self, use_aikars: bool = False) -> list[str]:
        """Returns the full command list for subprocess.Popen.
        If use_aikars=True, appends Aikar's optimized GC flags."""
        AIKARS_FLAGS = (
            "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 "
            "-XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC "
            "-XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 "
            "-XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M "
            "-XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 "
            "-XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 "
            "-XX:G1MixedGCLiveThresholdPercent=90 "
            "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 "
            "-Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true"
        )
        cmd = [self.java_path, self.xms_flag, self.xmx_flag]
        if use_aikars:
            cmd.extend(AIKARS_FLAGS.split())
        if self.extra_jvm_flags.strip():
            cmd.extend(self.extra_jvm_flags.strip().split())
        cmd.extend(["-jar", self.server_jar_path, "--nogui"])
        return cmd


def load_config() -> ServerConfig:
    """Loads config from disk. Returns defaults if file doesn't exist."""
    if not os.path.isfile(CONFIG_FILE):
        return ServerConfig()
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        # Use dataclass field names as keys; ignore unknown keys gracefully
        known_fields = ServerConfig.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return ServerConfig(**filtered)
    except (json.JSONDecodeError, TypeError):
        return ServerConfig()


def save_config(config: ServerConfig) -> None:
    """Persists the config dataclass to disk as JSON."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(asdict(config), f, indent=2)
