#!/usr/bin/env python3
"""Apply the explicitly bounded SUSFS 2.3 compatibility profile for Linux 3.18.

This is not a full SUSFS port. Some 4.4-based hunks target VFS APIs which do not
exist in 3.18. We preserve those rejects as audit artifacts and disable the
corresponding features in Kconfig. Unknown rejects abort rather than being
silently discarded.
"""
from pathlib import Path
import re
import shutil
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
    "fs/notify/fdinfo.c.rej": "SUS_KSTAT/SUS_MOUNT fdinfo callback signatures differ in 3.18",
    "fs/proc/base.c.rej": "SUS_MAP/OPEN_REDIRECT integration deferred",
    "fs/proc/fd.c.rej": "SUS_KSTAT/SUS_MOUNT proc-fd output integration deferred",
    "fs/proc/task_mmu.c.rej": "SUS_MAP VMA reporting hook deferred",
    "fs/readdir.c.rej": "SUS_PATH directory enumeration hook deferred",
    "fs/stat.c.rej": "SUS_KSTAT getattr compatibility hook deferred",
    "fs/super.c.rej": "SUS_MOUNT superblock integration deferred",
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
    "SUSFS v2.3 Linux 3.18 candidate profile — NOT full feature parity\n"
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
    "compat_profile=partial-susfs23-legacy-kernel\n"
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
print("Applied bounded SUSFS 2.3 profile; five incompatible feature families deferred and all rejects archived.")
