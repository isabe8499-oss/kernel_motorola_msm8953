#!/usr/bin/env python3
"""Hard gate for the complete Mimir 3.18.140 feature build.

The gate intentionally refuses to package a partial kernel. It runs after the
pinned BakaSU/SUSFS staging scripts and before invoking the build helper.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFCONFIG = ROOT / "arch/arm64/configs/deen_defconfig"
KSU = ROOT / "KernelSU"
SUSFS_C = ROOT / "fs/susfs.c"
SUSFS_H = ROOT / "include/linux/susfs.h"
SUSFS_DEF_H = ROOT / "include/linux/susfs_def.h"

required_symbols = [
    "CONFIG_KSU=y",
    "CONFIG_KSU_MANUAL_HOOK=y",
    "CONFIG_KSU_SUSFS=y",
    "CONFIG_KSU_SUSFS_SUS_PATH=y",
    "CONFIG_KSU_SUSFS_SUS_MOUNT=y",
    "CONFIG_KSU_SUSFS_SUS_KSTAT=y",
    "CONFIG_KSU_SUSFS_SUS_MAP=y",
    "CONFIG_KSU_SUSFS_OPEN_REDIRECT=y",
    "CONFIG_KSU_SUSFS_SPOOF_UNAME=y",
    "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y",
    "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y",
    "CONFIG_KSU_SUSFS_ENABLE_LOG=y",
    "CONFIG_NOMOUNT=y",
]

missing = []
if not DEFCONFIG.is_file():
    missing.append("missing arch/arm64/configs/deen_defconfig")
    config_text = ""
else:
    config_text = DEFCONFIG.read_text(errors="replace")
    for symbol in required_symbols:
        if symbol not in config_text.splitlines():
            missing.append(f"deen_defconfig: {symbol}")

if not KSU.exists():
    missing.append("BakaSU submodule directory KernelSU is missing")
else:
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(KSU), "rev-parse", "HEAD"], text=True
        ).strip()
        expected = "5785bdb8091304322f597f67d50e0b79f9815cb2"
        if actual != expected:
            missing.append(f"BakaSU pin mismatch: expected {expected}, got {actual}")
        for rel in ("kernel/Kconfig", "kernel/Kbuild"):
            if not (KSU / rel).is_file():
                missing.append(f"BakaSU source missing KernelSU/{rel}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing.append("KernelSU is not a valid initialized Git submodule")

for path in (SUSFS_C, SUSFS_H, SUSFS_DEF_H):
    if not path.is_file():
        missing.append(f"staged SUSFS source missing: {path.relative_to(ROOT)}")
if SUSFS_H.is_file():
    header = SUSFS_H.read_text(errors="replace")
    if '#define SUSFS_VERSION "v2.2.0"' not in header:
        missing.append("staged SUSFS source is not tagged v2.2.0")

# These feature hooks must exist in the kernel tree, not merely in Kconfig.
hook_checks = {
    "fs/namei.c": ("susfs_is_inode_sus_path", "susfs_open_redirect_spoof_do_sys_openat"),
    "fs/stat.c": ("susfs_sus_kstat_spoof_generic_fillattr",),
    "mm": ("susfs_sus_kstat_spoof_show_map_vma",),
    "drivers/kernelsu": ("susfs_init",),
}
for rel, markers in hook_checks.items():
    path = ROOT / rel
    if rel == "mm":
        candidates = list((ROOT / "mm").glob("*.c"))
        content = "\n".join(p.read_text(errors="replace") for p in candidates)
    elif rel == "drivers/kernelsu":
        candidates = list((ROOT / "KernelSU/kernel").rglob("*.c"))
        content = "\n".join(p.read_text(errors="replace") for p in candidates)
    elif path.is_file():
        content = path.read_text(errors="replace")
    else:
        content = ""
    for marker in markers:
        if marker not in content:
            missing.append(f"missing SUSFS integration hook {marker} ({rel})")

# Require a source-level NoMount port and protocol v22 declaration.
nomount_candidates = [
    ROOT / "fs/nomount/nomount.c",
    ROOT / "fs/nomount/Makefile",
    ROOT / "fs/nomount/Kconfig",
]
for path in nomount_candidates:
    if not path.is_file():
        missing.append(f"NoMount Linux 3.18 port missing: {path.relative_to(ROOT)}")
nomount_text = ""
nomount_header = ""
if nomount_candidates[0].is_file():
    nomount_text = nomount_candidates[0].read_text(errors="replace")
if (ROOT / "fs/nomount/nomount.h").is_file():
    nomount_header = (ROOT / "fs/nomount/nomount.h").read_text(errors="replace")
if '#define NOMOUNT_BASE_VERSION "22"' not in nomount_header:
    missing.append("NoMount source is not the pinned v2.2.0/protocol-22 implementation")
if "#define NM_LINUX_318_PORT 1" not in nomount_header:
    missing.append("NoMount Linux 3.18 compatibility port marker is missing")

if missing:
    print("MIMIR INTEGRATION GATE: BLOCKED — refusing to produce a flashable ZIP.")
    for item in missing:
        print(f" - {item}")
    print("\nThis is intentional: the current tree does not yet prove the complete")
    print("BakaSU + SUSFS 2.2.0 + NoMount 2.2.0 integration.")
    sys.exit(1)

if missing:
    report = [
        "MIMIR INTEGRATION GATE: BLOCKED — refusing to produce a flashable ZIP.",
        *[f" - {item}" for item in missing],
        "",
        "The current tree does not yet prove the complete BakaSU + SUSFS 2.2.0 + NoMount 2.2.0 integration.",
    ]
    print("\n".join(report))
    (ROOT / "mimir-integration-gate.txt").write_text("\n".join(report) + "\n")
    sys.exit(1)

success = [
    "MIMIR INTEGRATION GATE: PASS",
    "BakaSU Manual Hook, SUSFS 2.2.0 hooks and NoMount protocol v22 are present.",
]
print("\n".join(success))
(ROOT / "mimir-integration-gate.txt").write_text("\n".join(success) + "\n")
