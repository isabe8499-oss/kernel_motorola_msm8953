#!/usr/bin/env python3
"""Stage the pinned NoMount v2.2.0 sources; leave the driver disabled.

The upstream source is not Linux 3.18-compatible yet. This script records the
exact source snapshot in fs/nomount and wires its Kconfig/Makefile entries,
but forces default n so an incomplete port is never compiled accidentally.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "NoMount/kernel/src"
TARGET = ROOT / "fs/nomount"
FILES = ("nomount.c", "nomount.h", "Kconfig", "Makefile")
EXPECTED = "bf1847f98fed382369c43bfd652cd93774b9b8e3"

import subprocess
actual = subprocess.check_output(
    ["git", "-C", str(ROOT / "NoMount"), "rev-parse", "HEAD"], text=True
).strip()
if actual != EXPECTED:
    raise SystemExit(f"NoMount pin mismatch: expected {EXPECTED}, got {actual}")

for name in FILES:
    source = UPSTREAM / name
    if not source.is_file():
        raise SystemExit(f"Missing pinned NoMount source: {source}")
    TARGET.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, TARGET / name)

kconfig = TARGET / "Kconfig"
text = kconfig.read_text()
if "default y" in text:
    text = text.replace("default y", "default n", 1)
kconfig.write_text(text)

fs_kconfig = ROOT / "fs/Kconfig"
text = fs_kconfig.read_text()
entry = 'source "fs/nomount/Kconfig"'
if entry not in text:
    fs_kconfig.write_text(text.rstrip() + "\n\n" + entry + "\n")

fs_makefile = ROOT / "fs/Makefile"
text = fs_makefile.read_text()
entry = "obj-$(CONFIG_NOMOUNT) += nomount/"
if entry not in text:
    fs_makefile.write_text(text.rstrip() + "\n\n" + entry + "\n")

print(f"Staged NoMount v2.2.0 ({actual}) under fs/nomount.")
print("CONFIG_NOMOUNT defaults to n until the Linux 3.18 port is complete.")
