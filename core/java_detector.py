"""
core/java_detector.py
Scans the system for installed Java runtimes and checks version compatibility.
Minecraft 1.21+ requires Java 21. Minecraft 1.17-1.20 requires Java 17.
"""
import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional


# Minimum Java version required for modern Minecraft (1.21+)
MIN_JAVA_VERSION = 21


@dataclass
class JavaInstall:
    path: str          # Full path to the java binary
    version: int       # Major version number (e.g. 21)
    version_string: str  # Full version string for display


def _parse_major_version(version_str: str) -> Optional[int]:
    """
    Parses a java -version output string into a major version integer.
    Handles both old-style '1.8.0_xxx' and new-style '17.0.x' / '21.0.x'.
    """
    try:
        # Strip quotes if present
        v = version_str.strip().strip('"')
        parts = v.split(".")
        major = int(parts[0])
        # Old-style: '1.8' → major=8
        if major == 1 and len(parts) > 1:
            return int(parts[1])
        return major
    except (ValueError, IndexError):
        return None


def probe_java(java_path: str) -> Optional[JavaInstall]:
    """
    Runs `java -version` on the given binary path and returns a JavaInstall
    if successful, or None if the binary is not a valid Java runtime.
    """
    try:
        result = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # java -version writes to stderr (yes, really)
        output = result.stderr or result.stdout
        for line in output.splitlines():
            if "version" in line.lower():
                # e.g. 'openjdk version "21.0.3" 2024-04-16'
                parts = line.split('"')
                if len(parts) >= 2:
                    version_str = parts[1]
                    major = _parse_major_version(version_str)
                    if major is not None:
                        return JavaInstall(
                            path=java_path,
                            version=major,
                            version_string=version_str,
                        )
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        pass
    return None


def find_java_installations() -> list[JavaInstall]:
    """
    Searches for Java installations in common locations:
    1. $PATH (via `which java`)
    2. Common Linux JVM directories
    Returns a sorted list of JavaInstall objects (highest version first).
    """
    candidates: set[str] = set()

    # 1. Check $PATH first — most likely to be the user's intended Java
    which_java = shutil.which("java")
    if which_java:
        candidates.add(which_java)

    # 2. Scan common Linux JVM install directories
    import os
    jvm_dirs = [
        "/usr/lib/jvm",
        "/usr/local/lib/jvm",
        "/opt/java",
        "/opt/jdk",
    ]
    for jvm_dir in jvm_dirs:
        if os.path.isdir(jvm_dir):
            for entry in os.scandir(jvm_dir):
                if entry.is_dir():
                    java_bin = os.path.join(entry.path, "bin", "java")
                    if os.path.isfile(java_bin):
                        candidates.add(java_bin)

    # Probe each candidate
    installs: list[JavaInstall] = []
    for path in candidates:
        install = probe_java(path)
        if install:
            installs.append(install)

    # Sort by version descending so the best option comes first
    installs.sort(key=lambda j: j.version, reverse=True)
    return installs


def get_best_java(min_version: int = MIN_JAVA_VERSION) -> Optional[JavaInstall]:
    """Returns the highest-version Java install that meets the minimum requirement."""
    for install in find_java_installations():
        if install.version >= min_version:
            return install
    return None
