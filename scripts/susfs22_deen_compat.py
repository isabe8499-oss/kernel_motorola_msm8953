#!/usr/bin/env python3
"""Apply the explicitly bounded SUSFS 2.2 compatibility profile for Linux 3.18.

This is not a full SUSFS port. Some 4.4-based hunks target VFS APIs which do not
exist in 3.18. We preserve those rejects as audit artifacts and disable the
corresponding features in Kconfig. Unknown rejects abort rather than being
silently discarded.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
artifacts = Path(sys.argv[2] if len(sys.argv) > 2 else "artifacts").resolve()
status_path = artifacts / "patch-status.txt"
prior_status = status_path.read_text() if status_path.exists() else ""
if not re.search(r"(?m)^inline_hooks_exit=0$", prior_status):
    raise SystemExit("Inline hook script did not exit cleanly; refusing compatibility adaptation")
core_match = re.search(r"(?m)^core_patch_exit=(\d+)$", prior_status)
if not core_match:
    raise SystemExit("Core patch exit status is missing; refusing compatibility adaptation")
core_exit = core_match.group(1)
deferred_dir = artifacts / "deferred-hunks"
deferred_dir.mkdir(parents=True, exist_ok=True)

# These rejected hunks are exclusively behind features disabled by this
# allowlisted candidate profile; review the source hunks before changing this.
deferred = {
    "fs/namei.c.rej": "SUS_PATH and OPEN_REDIRECT rely on newer namei/path_openat APIs",
    "fs/namespace.c.rej": "SUS_MOUNT requires Linux 3.18 mount namespace adaptation",
    "fs/notify/fdinfo.c.rej": "SUS_MOUNT fdinfo callback signatures differ in 3.18",
    "fs/proc/base.c.rej": "OPEN_REDIRECT integration deferred",
    "fs/proc/fd.c.rej": "SUS_MOUNT proc-fd output integration deferred",
    "fs/proc/task_mmu.c.rej": "SUS_MAP VMA reporting hook deferred",
    "fs/readdir.c.rej": "SUS_PATH directory enumeration hook deferred",
}
found = {
    p.relative_to(root).as_posix(): p
    for p in root.rglob("*.rej")
    if ".git" not in p.parts and artifacts not in p.parents
}
unknown = sorted(set(found) - set(deferred) - {"security/selinux/avc.c.rej"})
missing = sorted(set(deferred) - set(found))
if unknown:
    raise SystemExit("Unknown reject files; refusing to discard: " + ", ".join(unknown))
if missing:
    raise SystemExit("Expected deferred reject file missing; review changed patch behavior: " + ", ".join(missing))

# The AVC core patch's only rejected hunk is a common label required by a
# successful goto bypass_orig_flow. Add it at the exact Linux 3.18 site.
avc = root / "security/selinux/avc.c"
source = avc.read_text()
label = "#ifdef CONFIG_KSU_SUSFS\nbypass_orig_flow:\n#endif // CONFIG_KSU_SUSFS\n"
anchor = "\tBUG_ON(!tclass || tclass >= ARRAY_SIZE(secclass_map));"
if source.count("goto bypass_orig_flow;") < 1:
    raise SystemExit("AVC patch has no bypass_orig_flow goto; source differs from audited patch")
if label.strip() not in source:
    func_start = source.find("static void avc_dump_query(")
    if func_start < 0:
        raise SystemExit("avc_dump_query was not found; refusing unsafe edit")
    func_end = source.find("\n}", func_start)
    if func_end < 0:
        raise SystemExit("avc_dump_query closing brace was not found; refusing unsafe edit")
    func = source[func_start:func_end]
    anchors = [
        "\tBUG_ON(!tclass || tclass >= ARRAY_SIZE(secclass_map));",
        "\tBUG_ON(tclass >= ARRAY_SIZE(secclass_map));",
    ]
    matches = [candidate for candidate in anchors if func.count(candidate) == 1]
    if len(matches) != 1:
        raise SystemExit("AVC label insertion anchor is not unique inside avc_dump_query; refusing unsafe edit")
    target = matches[0]
    func = func.replace(target, label + target, 1)
    source = source[:func_start] + func + source[func_end:]
    avc.write_text(source)

# Linux 3.18 inline hooks operate on user pointers; BakaSU's CONFIG_KSU_SUSFS
# signatures use struct filename only on newer VFS implementations. Select the
# legacy signature/implementation on this old kernel, while retaining SUSFS.
bakasu_header = root / "drivers/kernelsu/feature/sucompat.h"
header_text = bakasu_header.read_text()
if "#include <linux/version.h>" not in header_text:
    header_text = header_text.replace("#include <linux/types.h>", "#include <linux/types.h>\n#include <linux/version.h>", 1)
old_decl = """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);

int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);"""
new_decl = """#if defined(CONFIG_KSU_SUSFS) && LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);

int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);"""
if header_text.count(old_decl) != 1:
    raise SystemExit("BakaSU sucompat.h SUSFS declarations did not match exactly; refusing signature adaptation")
bakasu_header.write_text(header_text.replace(old_decl, new_decl, 1))

bakasu_source = root / "drivers/kernelsu/feature/sucompat.c"
source_text = bakasu_source.read_text()
for fn in ("ksu_handle_faccessat", "ksu_handle_stat"):
    marker = "#ifdef CONFIG_KSU_SUSFS\nint " + fn + "("
    replacement = "#if defined(CONFIG_KSU_SUSFS) && LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)\nint " + fn + "("
    if source_text.count(marker) != 1:
        raise SystemExit(f"BakaSU sucompat.c {fn} implementation marker not unique; refusing signature adaptation")
    source_text = source_text.replace(marker, replacement, 1)
bakasu_source.write_text(source_text)

# The 3.18 tree has bool-based sucompat, while SUSFS's newer inline patch assumes
# the modern static-key representation for this particular flag.
for rel in ("fs/open.c", "fs/stat.c", "fs/exec.c"):
    path = root / rel
    text = path.read_text()
    text = text.replace("extern struct static_key_true ksu_su_compat_enabled;", "extern bool ksu_su_compat_enabled;")
    text = text.replace("extern struct static_key ksu_su_compat_enabled;", "extern bool ksu_su_compat_enabled;")
    text = text.replace("static_branch_likely(&ksu_su_compat_enabled)", "ksu_su_compat_enabled")
    text = text.replace("static_branch_unlikely(&ksu_su_compat_enabled)", "ksu_su_compat_enabled")
    text = text.replace("static_key_enabled(&ksu_su_compat_enabled)", "ksu_su_compat_enabled")
    path.write_text(text)

# BakaSU currently has a deliberate SUSFS compatibility stop. The isolated
# candidate removes only that unconditional make-time stop; all compiler and
# hook checks remain enabled.
compat_mk = root / "drivers/kernelsu/tools/susfs_compat.mk"
compat_text = compat_mk.read_text()
stop_line = "$(error Please wait susfs update.)"
if compat_text.count(stop_line) != 1:
    raise SystemExit("Expected BakaSU SUSFS compatibility stop not found exactly once")
compat_mk.write_text(compat_text.replace(stop_line + "\n", "", 1))

# Backport the SUSFS patch set's newer header and static-key API to Linux 3.18.
defs = root / "include/linux/susfs_def.h"
defs_source = defs.read_text()
if defs_source.count("#include <linux/bits.h>") == 1:
    defs.write_text(defs_source.replace("#include <linux/bits.h>", "#include <linux/bitops.h>", 1))
elif "#include <linux/bitops.h>" not in defs_source:
    raise SystemExit("SUSFS header has neither linux/bits.h nor linux/bitops.h; review header API")

static_key_paths = [
    "fs/susfs.c",
    "kernel/sys.c",
    "fs/proc/cmdline.c",
    "fs/proc_namespace.c",
    "security/selinux/avc.c",
    "fs/namespace.c",
    "fs/super.c",
    "fs/proc/base.c",
    "fs/proc/fd.c",
    "fs/notify/fdinfo.c",
    "fs/proc/task_mmu.c",
    "fs/stat.c",
    "fs/read_write.c",
    "fs/open.c",
    "fs/exec.c",
    "kernel/reboot.c",
    "kernel/kallsyms.c",
    "security/security.c",
    "security/selinux/hooks.c",
    "drivers/input/input.c",
    "drivers/kernelsu/runtime/ksud_integration.c",
]
for rel in static_key_paths:
    path = root / rel
    if not path.is_file():
        continue
    text = path.read_text()
    before = text
    text = re.sub(r"\bDEFINE_STATIC_KEY_FALSE\((\w+)\);", r"struct static_key \1 = STATIC_KEY_INIT_FALSE;", text)
    text = re.sub(r"\bDEFINE_STATIC_KEY_TRUE\((\w+)\);", r"struct static_key \1 = STATIC_KEY_INIT_TRUE;", text)
    text = re.sub(r"\bstruct static_key_false\b", "struct static_key", text)
    text = re.sub(r"\bstruct static_key_true\b", "struct static_key", text)
    text = re.sub(r"\bstatic_branch_likely\s*\(", "static_key_enabled(", text)
    text = re.sub(r"\bstatic_branch_unlikely\s*\(", "static_key_enabled(", text)
    text = re.sub(r"\bstatic_branch_enable\s*\(", "static_key_slow_inc(", text)
    text = re.sub(r"\bstatic_branch_disable\s*\(", "static_key_slow_dec(", text)
    if text != before and (
        "static_key_enabled(" in text or
        "static_key_slow_inc(" in text or
        "static_key_slow_dec(" in text or
        "STATIC_KEY_INIT_FALSE" in text or
        "STATIC_KEY_INIT_TRUE" in text
    ):
        if "#include <linux/jump_label.h>" not in text:
            match = re.search(r"(?m)^#include <linux/[^>\n]+>\n", text)
            if not match:
                raise SystemExit(f"Could not find include anchor to add jump_label.h in {rel}")
            text = text[:match.end()] + "#include <linux/jump_label.h>\n" + text[match.end():]
    if text != before:
        path.write_text(text)

# Preserve every rejected hunk verbatim, then remove only the allowlisted
# .rej files because the candidate profile explicitly disables those features.
manifest = []
for rel, reason in deferred.items():
    src = found[rel]
    dst = deferred_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    manifest.append(f"{rel}\tDEFERRED\t{reason}")
    src.unlink()

avc_rej = found.get("security/selinux/avc.c.rej")
if avc_rej:
    dst = deferred_dir / "security/selinux/avc.c.rej"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(avc_rej, dst)
    avc_rej.unlink()
    manifest.append("security/selinux/avc.c.rej\tMANUALLY_ADAPTED\tAdded required bypass_orig_flow label at the 3.18 AVC flow")

# Normalize only whitespace artifacts introduced by the pinned patch/script.
ns = root / "fs/namespace.c"
ns_data = ns.read_text()
ns.write_text(ns_data.rstrip() + "\n")
rw = root / "fs/read_write.c"
rw_lines = rw.read_text().splitlines()
rw.write_text("\n".join(line.rstrip() if not line.strip() else line for line in rw_lines) + "\n")

(artifacts / "deferred-feature-contract.txt").write_text(
    "SUSFS v2.2 Linux 3.18 candidate profile — NOT full feature parity\n"
    "KSU_SUSFS_SUS_PATH=n\n"
    "KSU_SUSFS_SUS_MOUNT=n\n"
    "KSU_SUSFS_SUS_KSTAT=n\n"
    "KSU_SUSFS_OPEN_REDIRECT=n\n"
    "KSU_SUSFS_SUS_MAP=n\n"
    "KSU_SUSFS_SPOOF_UNAME=y\n"
    "KSU_SUSFS_ENABLE_LOG=y\n"
    "KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y\n"
    "KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y\n"
)
(artifacts / "hunk-disposition.tsv").write_text("\n".join(manifest) + "\n")
(artifacts / "patch-status.txt").write_text(
    f"core_patch_exit={core_exit} (raw patch status; remaining hunks are individually dispositioned)\n"
    "inline_hooks_exit=0\n"
    "compat_profile=partial-susfs22-legacy-kernel\n"
    "avc_label_adaptation=applied\n"
    f"deferred_hunk_files={len(deferred)}\n"
)
left = [
    p.relative_to(root).as_posix()
    for p in root.rglob("*.rej")
    if ".git" not in p.parts and artifacts not in p.parents
]
if left:
    raise SystemExit("Rejects remain after explicit disposition: " + ", ".join(left))
(artifacts / "rejected-files.txt").write_text(
    "No unclassified live .rej files remain. Deferred hunks were preserved verbatim under artifacts/deferred-hunks/.\n"
)
print("Applied bounded SUSFS 2.2 profile; incompatible feature families deferred, legacy BakaSU signatures adapted, and rejects archived.")
