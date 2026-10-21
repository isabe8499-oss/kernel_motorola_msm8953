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
    "fs/namei.c.rej": "SUS_PATH and OPEN_REDIRECT entry integration adapted to Linux 3.18",
    "fs/namespace.c.rej": "SUS_MOUNT code adapted for Linux 3.18; enabled only in staged candidate build",
    "fs/notify/fdinfo.c.rej": "SUS_MOUNT fdinfo callback signatures and inode spoof adapted for Linux 3.18",
    "fs/proc/base.c.rej": "OPEN_REDIRECT proc readlink integration adapted to Linux 3.18",
    "fs/proc/fd.c.rej": "SUS_MOUNT proc-fd output adapted for Linux 3.18",
    "fs/proc/task_mmu.c.rej": "SUS_MAP show_smap hunk adapted to Linux 3.18; enabled only in staged candidate build",
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

# The pinned 2026 BakaSU tree expects the newer SUSFS no_su API, which is
# absent from the legacy v2.2/4.4 patch. Backport the API using ARM64 thread flags.
# TIF 62 is the spare non-privilege flag used by BakaSU's own manual-hook path;
# TIF 32 records the zygote-next marker (the legacy SUSFS core has no consumer).
def_path = root / "include/linux/susfs_def.h"
def_text = def_path.read_text()
api_block = """
#include <linux/sched.h>
#include <linux/thread_info.h>
#ifndef TIF_PROC_NON_PRIVILEGE
#define TIF_PROC_NON_PRIVILEGE 62
#endif
#ifndef TIF_PROC_UMOUNTED_FOR_ZYGOTE_NEXT
#define TIF_PROC_UMOUNTED_FOR_ZYGOTE_NEXT 32
#endif
static inline bool susfs_is_current_proc_no_su(void)
{
    return test_thread_flag(TIF_PROC_NON_PRIVILEGE);
}
static inline void susfs_set_current_proc_no_su(void)
{
    set_thread_flag(TIF_PROC_NON_PRIVILEGE);
}
static inline void susfs_clear_current_proc_no_su(void)
{
    clear_thread_flag(TIF_PROC_NON_PRIVILEGE);
}
static inline void susfs_set_current_proc_umounted_for_zygote_next(void)
{
    set_thread_flag(TIF_PROC_UMOUNTED_FOR_ZYGOTE_NEXT);
}
"""
if "static inline bool susfs_is_current_proc_no_su(void)" not in def_text:
    final_guard = "#endif // #ifndef KSU_SUSFS_DEF_H"
    if def_text.count(final_guard) != 1:
        raise SystemExit("SUSFS header final guard not unique; refusing to add legacy no_su API")
    def_text = def_text.replace(final_guard, api_block + "\n" + final_guard, 1)
    def_path.write_text(def_text)

# The generic legacy inline-hook script injects ksu_bprm_check(), which this
# pinned BakaSU revision does not implement. BakaSU's own hook set handles its
# exec/credential path; remove only that stale declaration and call.
security_path = root / "security/security.c"
security_text = security_path.read_text()
security_text, call_count = re.subn(
    r"(?m)^\s*#ifdef CONFIG_KSU\n\s*ksu_bprm_check\(bprm\);\n\s*#endif\n",
    "",
    security_text,
)
security_text, decl_count = re.subn(
    r"(?m)^\s*extern int ksu_bprm_check\(struct linux_binprm \*bprm\);\n",
    "",
    security_text,
)
if call_count > 1 or decl_count > 1:
    raise SystemExit("Unexpected duplicate ksu_bprm_check hook; refusing unsafe removal")
if call_count == 0:
    if "ksu_bprm_check(bprm);" in security_text:
        raise SystemExit("Unrecognized ksu_bprm_check call remains in security.c")
security_path.write_text(security_text)

# On 3.18 BakaSU intentionally uses a bool for ksu_su_compat_enabled. The
# SUSFS-specific handlers in this revision assume a modern static key, so gate
# those two checks on the same compatibility macro used by the rest of BakaSU.
source_text = bakasu_source.read_text()
for fn in ("ksu_handle_faccessat", "ksu_handle_stat"):
    start_marker = "#if defined(CONFIG_KSU_SUSFS) && LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)\nint " + fn + "("
    start = source_text.find(start_marker)
    end_marker = "\n#else\nint " + fn + "("
    end = source_text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit(f"Cannot locate versioned SUSFS handler for {fn}")
    block = source_text[start:end]
    old_check = "if (!static_branch_unlikely(&ksu_su_compat_enabled)) {"
    if block.count(old_check) != 1:
        raise SystemExit(f"Expected one modern static-key check in {fn}; refusing unsafe edit")
    new_check = """#ifdef KSU_COMPAT_USE_STATIC_KEY
    if (!static_branch_unlikely(&ksu_su_compat_enabled)) {
#else
    if (!ksu_su_compat_enabled) {
#endif"""
    block = block.replace(old_check, new_check, 1)
    source_text = source_text[:start] + block + source_text[end:]
bakasu_source.write_text(source_text)

# The generic SUSFS inline script injects legacy KernelSU hooks into
# security/security.c. BakaSU explicitly marks ksu_handle_rename as incompatible
# with its manual-hook integration; rename mediation must use the supported LSM
# path. Remove every exact legacy declaration/call block, then reject leftovers.
security_text = security_path.read_text()
security_text, rename_call_count = re.subn(
    r"(?m)^[ \t]*#ifdef CONFIG_KSU[ \t]*\n[ \t]*ksu_handle_rename\(old_dentry, new_dentry\);[ \t]*\n[ \t]*#endif[ \t]*\n",
    "",
    security_text,
)
security_text, rename_decl_count = re.subn(
    r"(?m)^[ \t]*extern int ksu_handle_rename\(struct dentry \*old_dentry, struct dentry \*new_dentry\);[ \t]*\n",
    "",
    security_text,
)
# The inline patch can insert the call at more than one matching legacy site;
# all such references are incompatible with BakaSU Manual Hook.
if "ksu_handle_rename" in security_text:
    raise SystemExit("Unrecognized ksu_handle_rename reference remains in security/security.c")
security_path.write_text(security_text)

# The generic script also injects an old KernelSU credential hook with
# struct cred * arguments. BakaSU's ksu_handle_setuid() instead accepts uid_t
# values and is already wired by its own setuid hook; remove the mismatched call.
security_text = security_path.read_text()
security_text, setuid_call_count = re.subn(
    r"(?m)^\s*ksu_handle_setuid\(new, old\);\s*\n",
    "",
    security_text,
)
security_text, setuid_decl_count = re.subn(
    r"(?m)^\s*extern int ksu_handle_setuid\(struct cred \*new, const struct cred \*old\);\s*\n",
    "",
    security_text,
)
if setuid_call_count > 1 or setuid_decl_count > 1:
    raise SystemExit("Unexpected duplicate generic ksu_handle_setuid hook")
security_path.write_text(security_text)

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

# The upstream v2.2 hook script assumes do_execveat_common(fd, ..., flags),
# which does not exist in this Linux 3.18 tree. This tree's do_execve_common()
# represents execve() only, so provide its correct legacy values (AT_FDCWD, 0)
# and the missing declarations rather than leaving undefined fd/flags variables.
exec_path = root / "fs/exec.c"
exec_source = exec_path.read_text()
if "#include <linux/susfs_def.h>" not in exec_source:
    include_anchor = "#include <linux/namei.h>\n"
    if exec_source.count(include_anchor) != 1:
        raise SystemExit("Could not uniquely locate exec.c namei include for SUSFS declarations")
    exec_source = exec_source.replace(
        include_anchor,
        include_anchor + "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#include <linux/jump_label.h>\n#endif\n",
        1
    )
decl_anchor = "static int do_execve_common(struct filename *filename,\n\t\t\t\tstruct user_arg_ptr argv,\n\t\t\t\tstruct user_arg_ptr envp)\n{"
decls = """#ifdef CONFIG_KSU_SUSFS
extern bool ksu_su_compat_enabled;
extern struct static_key susfs_is_sdcard_android_data_not_decrypted;
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);
extern int ksu_handle_execveat_sucompat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);
#endif

"""
if exec_source.count(decl_anchor) != 1:
    raise SystemExit("Linux 3.18 do_execve_common marker not unique; refusing exec hook adaptation")
if "extern int ksu_handle_execveat_sucompat" not in exec_source:
    exec_source = exec_source.replace(decl_anchor, decls + decl_anchor, 1)
local_anchor = decl_anchor
local_replacement = local_anchor + """
#ifdef CONFIG_KSU_SUSFS
\tint fd = AT_FDCWD;
\tint flags = 0;
#endif"""
if exec_source.count(local_anchor) != 1:
    raise SystemExit("Linux 3.18 do_execve_common local insertion point not unique")
if "int fd = AT_FDCWD;" not in exec_source:
    exec_source = exec_source.replace(local_anchor, local_replacement, 1)
exec_path.write_text(exec_source)

# BakaSU currently has a deliberate SUSFS compatibility stop. The isolated
# candidate removes only that unconditional make-time stop; all compiler and
# hook checks remain enabled.
compat_candidates = [
    root / "KernelSU/kernel/tools/susfs_compat.mk",
    root / "drivers/kernelsu/tools/susfs_compat.mk",
]
compat_mk = next((p for p in compat_candidates if p.is_file()), None)
if compat_mk is None:
    raise SystemExit("BakaSU susfs_compat.mk not found in either checkout or driver symlink")
compat_text = compat_mk.read_text()
# Remove only the explicit make-time stop. Keep the diagnostic info() lines.
compat_text, removed = re.subn(
    r"(?m)^\s*\$\(error\s+Please wait susfs update\.\)\s*$\n?",
    "# Candidate build: upstream SUSFS compatibility stop bypassed after applying the pinned legacy adapter.\n",
    compat_text,
    count=1,
)
if removed != 1 or "$(error Please wait susfs update.)" in compat_text:
    raise SystemExit("Could not remove and verify the single BakaSU SUSFS make-time stop")
compat_mk.write_text(compat_text)
if "$(error Please wait susfs update.)" in compat_mk.read_text():
    raise SystemExit("BakaSU SUSFS make-time stop remains after compatibility edit")


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


# Linux 3.18 SUS_PATH compatibility: its nameidata structure is in the public
# header and path_init replaces the newer set_nameidata helper.
nh_path = root / "include/linux/namei.h"
nh = nh_path.read_text()
if "unsigned int\tstate;" not in nh:
    anchor = "\tunsigned int\tflags;\n"
    if nh.count(anchor) != 1:
        raise SystemExit("nameidata flags anchor mismatch; refusing SUS_PATH port")
    nh = nh.replace(anchor, anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tunsigned int\tstate;\n#endif\n", 1)
    nh_path.write_text(nh)

np = root / "fs/namei.c"
ns = np.read_text()
p0 = ns.find("static int path_init(")
p1 = ns.find("\n}", p0)
if p0 < 0 or p1 < 0:
    raise SystemExit("Linux 3.18 path_init not found")
pf = ns[p0:p1]
if "nd->state = 0;" not in pf:
    anchor = "\tint retval = 0;\n"
    if pf.count(anchor) != 1:
        raise SystemExit("path_init state initialization anchor mismatch")
    pf = pf.replace(anchor, anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tnd->state = 0;\n#endif\n", 1)
    ns = ns[:p0] + pf + ns[p1:]

l0 = ns.find("static inline int lookup_last(struct nameidata *nd, struct path *path)")
l1 = ns.find("\n}", l0)
if l0 < 0 or l1 < 0:
    raise SystemExit("Linux 3.18 lookup_last not found")
lf = ns[l0:l1]
if "ND_STATE_LOOKUP_LAST" not in lf:
    brace = lf.find("{")
    lf = lf[:brace + 1] + "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tnd->state |= ND_STATE_LOOKUP_LAST;\n#endif\n" + lf[brace + 1:]
    ns = ns[:l0] + lf + ns[l1:]

d0 = ns.find("static int do_last(struct nameidata *nd, struct path *path")
d1 = ns.find("\n}", d0)
if d0 < 0 or d1 < 0:
    raise SystemExit("Linux 3.18 do_last not found")
df = ns[d0:d1]
if "ND_STATE_OPEN_LAST" not in df:
    brace = df.find("{")
    df = df[:brace + 1] + "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tnd->state |= ND_STATE_OPEN_LAST;\n#endif\n" + df[brace + 1:]
    ns = ns[:d0] + df + ns[d1:]

w0 = ns.find("static inline int walk_component(struct nameidata *nd, struct path *path,")
w1 = ns.find("\n}", w0)
if w0 < 0 or w1 < 0:
    raise SystemExit("Linux 3.18 walk_component not found")
wf = ns[w0:w1]
if "susfs_is_inode_sus_path(inode)" not in wf:
    anchor = "\tif (!inode || d_is_negative(path->dentry))\n\t\tgoto out_path_put;\n"
    if wf.count(anchor) != 1:
        raise SystemExit("walk_component SUS_PATH anchor mismatch")
    extra = anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tif (inode && susfs_is_inode_sus_path(inode)) {\n\t\terr = -ENOENT;\n\t\tgoto out_path_put;\n\t}\n#endif\n"
    wf = wf.replace(anchor, extra, 1)
    ns = ns[:w0] + wf + ns[w1:]
np.write_text(ns)

# Apply the rejected fillonedir hunk using the actual Linux 3.18 callback.
rp = root / "fs/readdir.c"
rs = rp.read_text()
r0 = rs.find("static int fillonedir(")
r1 = rs.find("\n}", r0)
if r0 < 0 or r1 < 0:
    raise SystemExit("fillonedir callback not found")
rf = rs[r0:r1]
if "struct inode *inode;" not in rf:
    anchor = "\tunsigned long d_ino;\n"
    if rf.count(anchor) != 1:
        raise SystemExit("fillonedir inode declaration anchor mismatch")
    rf = rf.replace(anchor, anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tstruct inode *inode;\n#endif\n", 1)
if "susfs_is_inode_sus_path(inode)" not in rf:
    anchor = "\tif (sizeof(d_ino) < sizeof(ino) && d_ino != ino) {\n\t\tbuf->result = -EOVERFLOW;\n\t\treturn -EOVERFLOW;\n\t}\n"
    if rf.count(anchor) != 1:
        raise SystemExit("fillonedir SUS_PATH anchor mismatch")
    extra = anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tinode = ilookup(buf->sb, ino);\n\tif (inode) {\n\t\tif (susfs_is_inode_sus_path(inode)) {\n\t\t\tiput(inode);\n\t\t\treturn 0;\n\t\t}\n\t\tiput(inode);\n\t}\n#endif\n"
    rf = rf.replace(anchor, extra, 1)
    rs = rs[:r0] + rf + rs[r1:]
rp.write_text(rs)


# Adapt the rejected SUS_MAP smaps hunk to the Linux 3.18 show_smap layout.
mm_path = root / "fs/proc/task_mmu.c"
mm = mm_path.read_text()
sm0 = mm.find("static int show_smap(")
sm1 = mm.find("\n}", sm0)
if sm0 < 0 or sm1 < 0:
    raise SystemExit("Linux 3.18 show_smap not found; refusing SUS_MAP port")
smf = mm[sm0:sm1]
if "SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))" not in smf:
    anchor = "\tsmaps_walk.private = mss;\n"
    if smf.count(anchor) != 1:
        raise SystemExit("show_smap SUS_MAP insertion anchor mismatch")
    extra = "#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n\tif (vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))\n\t\treturn 0;\n#endif\n\n" + anchor
    smf = smf.replace(anchor, extra, 1)
    mm = mm[:sm0] + smf + mm[sm1:]
    mm_path.write_text(mm)


# Linux 3.18 SUS_MOUNT compatibility: restore the rejected namespace declarations.
mount_ns_path = root / "fs/namespace.c"
mount_ns = mount_ns_path.read_text()
task_work_anchor = "#include <linux/task_work.h>\n"
if "#include <linux/susfs_def.h>" not in mount_ns:
    if mount_ns.count(task_work_anchor) != 1:
        raise SystemExit("namespace.c SUS_MOUNT include anchor mismatch")
    mount_ns = mount_ns.replace(task_work_anchor, task_work_anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n#include <linux/susfs_def.h>\n#endif\n", 1)
mount_anchor = '#include "internal.h"\n'
if "extern bool susfs_is_current_ksu_domain(void);" not in mount_ns:
    defs = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\nextern bool susfs_is_current_ksu_domain(void);\nextern struct static_key susfs_is_sdcard_android_data_not_decrypted;\n#define CL_COPY_MNT_NS BIT(25)\n#endif\n\n"
    if mount_ns.count(mount_anchor) != 1:
        raise SystemExit("namespace.c SUS_MOUNT declaration anchor mismatch")
    mount_ns = mount_ns.replace(mount_anchor, mount_anchor + "\n" + defs, 1)
mount_ns_path.write_text(mount_ns)

# Replace the newer 4.4 mount allocator clones with wrappers around the
# native Linux 3.18 alloc_vfsmnt(), whose struct mount lacks fs_pin members.
helper_pattern = re.compile(
    r"(?s)#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n/\* A copy of alloc_vfsmnt\(\) but allocates the fake mnt_id.*?#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n(?=\nstatic struct mount \*alloc_vfsmnt)"
)
helper_replacement = """#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
static struct mount *alloc_vfsmnt(const char *name);

static struct mount *susfs_alloc_unshare_ksu_vfsmnt(const char *name, int old_mnt_id)
{
\tstruct mount *mnt = alloc_vfsmnt(name);
\tif (!mnt)
\t\treturn NULL;
\tmnt_free_id(mnt);
\tmnt->mnt_id = old_mnt_id;
\treturn mnt;
}

static struct mount *susfs_alloc_non_unshare_ksu_vfsmnt(const char *name)
{
\tstruct mount *mnt;
\tint fake_id = ida_simple_get(&mnt_id_ida, DEFAULT_KSU_MNT_ID, 0, GFP_KERNEL);
\tif (fake_id < 0)
\t\treturn NULL;
\tmnt = alloc_vfsmnt(name);
\tif (!mnt) {
\t\tida_simple_remove(&mnt_id_ida, fake_id);
\t\treturn NULL;
\t}
\tmnt_free_id(mnt);
\tmnt->mnt_id = fake_id;
\treturn mnt;
}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT

"""
mount_ns, helper_count = helper_pattern.subn(helper_replacement, mount_ns, count=1)
if helper_count != 1:
    raise SystemExit("Could not replace newer SUS_MOUNT mount allocators with Linux 3.18 wrappers")
mount_ns_path.write_text(mount_ns)

# Linux 3.18 fsnotify callbacks return int and carry a different callback type
# than the 4.4-based patch; adapt the callback signatures while preserving
# the original return semantics.
fdinfo_path = root / "fs/notify/fdinfo.c"
fi = fdinfo_path.read_text()
if "#include <linux/slab.h>" not in fi:
    include_anchor = "#include <linux/seq_file.h>\n"
    if fi.count(include_anchor) != 1:
        raise SystemExit("fdinfo.c slab include anchor mismatch")
    fi = fi.replace(include_anchor, "#include <linux/slab.h>\n" + include_anchor, 1)
if "#include <linux/susfs_def.h>" not in fi:
    include_anchor = "#include <linux/exportfs.h>\n"
    if fi.count(include_anchor) != 1:
        raise SystemExit("fdinfo.c SUSFS include anchor mismatch")
    fi = fi.replace(include_anchor, include_anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n#include <linux/susfs_def.h>\n#endif\n", 1)

old_show_sig = "static int show_fdinfo(struct seq_file *m, struct file *f,\n\t\t       int (*show)(struct seq_file *m, struct fsnotify_mark *mark))"
new_show_sig = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\nstatic int show_fdinfo(struct seq_file *m, struct file *f,\n\t\t       int (*show)(struct seq_file *m, struct fsnotify_mark *mark, struct file *file))\n#else\n" + old_show_sig + "\n#endif"
if "int (*show)(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)" not in fi:
    if fi.count(old_show_sig) != 1:
        raise SystemExit("fdinfo.c show_fdinfo signature anchor mismatch")
    fi = fi.replace(old_show_sig, new_show_sig, 1)
old_call = "\t\tret = show(m, mark);"
new_call = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n\t\tret = show(m, mark, f);\n#else\n\t\tret = show(m, mark);\n#endif"
if "ret = show(m, mark, f);" not in fi:
    if fi.count(old_call) != 1:
        raise SystemExit("fdinfo.c callback invocation anchor mismatch")
    fi = fi.replace(old_call, new_call, 1)

old_inotify_sig = "static int inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)"
new_inotify_sig = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\nstatic int inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n#else\n" + old_inotify_sig + "\n#endif"
if "static int inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)" not in fi:
    if fi.count(old_inotify_sig) != 1:
        raise SystemExit("fdinfo.c inotify_fdinfo signature anchor mismatch")
    fi = fi.replace(old_inotify_sig, new_inotify_sig, 1)

old_fanotify_sig = "static int fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)"
new_fanotify_sig = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\nstatic int fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n#else\n" + old_fanotify_sig + "\n#endif"
if "static int fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)" not in fi:
    if fi.count(old_fanotify_sig) != 1:
        raise SystemExit("fdinfo.c fanotify_fdinfo signature anchor mismatch")
    fi = fi.replace(old_fanotify_sig, new_fanotify_sig, 1)
    fi = fi.replace("static int fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n#else\n" + old_fanotify_sig + "\n#endif\n{",
                    "static int fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n#else\n" + old_fanotify_sig + "\n#endif\n{\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n\t(void)file;\n#endif", 1)

# Insert the mount-path spoof in the inode-mark branch; use Linux 3.18's int
# callback and avoid newer VFS callback signatures.
inotify_anchor = "\tinode = igrab(mark->i.inode);\n\tif (inode) {\n"
if "susfs_is_current_proc_umounted()" not in fi:
    mount_code = """\t\t#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
\t\t{
\t\t\tstruct mount *mnt = real_mount(file->f_path.mnt);
\t\t\tif (mnt->mnt_id >= DEFAULT_KSU_MNT_ID && likely(susfs_is_current_proc_umounted())) {
\t\t\t\tchar *pathname = kmalloc(PAGE_SIZE, GFP_KERNEL);
\t\t\t\tif (pathname) {
\t\t\t\t\tchar *dpath = d_path(&file->f_path, pathname, PAGE_SIZE);
\t\t\t\t\tstruct path path;
\t\t\t\t\tif (!IS_ERR_OR_NULL(dpath) && !kern_path(dpath, 0, &path)) {
\t\t\t\t\t\tif (path.dentry->d_inode) {
\t\t\t\t\t\t\tseq_printf(m, "inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:%x ",
\t\t\t\t\t\t\t\tinode_mark->wd, path.dentry->d_inode->i_ino,
\t\t\t\t\t\t\t\tpath.dentry->d_inode->i_sb->s_dev,
\t\t\t\t\t\t\t\tmark->mask & IN_ALL_EVENTS, mark->ignored_mask);
\t\t\t\t\t\t\tshow_mark_fhandle(m, path.dentry->d_inode);
\t\t\t\t\t\t\tseq_putc(m, '\\\\n');
\t\t\t\t\t\t\tpath_put(&path);
\t\t\t\t\t\t\tkfree(pathname);
\t\t\t\t\t\t\tiput(inode);
\t\t\t\t\t\t\treturn 0;
\t\t\t\t\t\t}
\t\t\t\t\t\tpath_put(&path);
\t\t\t\t\t}
\t\t\t\t\tkfree(pathname);
\t\t\t\t}
\t\t\t}
\t\t}
\t\t#endif
"""
    if fi.count(inotify_anchor) != 1:
        raise SystemExit("fdinfo.c inotify mount spoof insertion anchor mismatch")
    fi = fi.replace(inotify_anchor, inotify_anchor + mount_code, 1)
fdinfo_path.write_text(fi)

# The core patch already applies proc/fd declarations; adapt its rejected seq_show
# hunk to Linux 3.18's conditional body.
procfd_path = root / "fs/proc/fd.c"
pf = procfd_path.read_text()
if "#include <linux/slab.h>" not in pf:
    include_anchor = "#include <linux/seq_file.h>\n"
    if pf.count(include_anchor) != 1:
        raise SystemExit("proc/fd.c slab include anchor mismatch")
    pf = pf.replace(include_anchor, "#include <linux/slab.h>\n" + include_anchor, 1)
if "#include <linux/susfs_def.h>" not in pf:
    include_anchor = "#include <linux/proc_fs.h>\n"
    if pf.count(include_anchor) != 1:
        raise SystemExit("proc/fd.c SUSFS include anchor mismatch")
    pf = pf.replace(include_anchor, include_anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n#include <linux/susfs_def.h>\n#endif\n", 1)
if "extern int susfs_get_non_sus_mnt_id_from_mnt" not in pf:
    include_anchor = '#include "fd.h"\n'
    if pf.count(include_anchor) != 1:
        raise SystemExit("proc/fd.c SUSFS mount prototype anchor mismatch")
    pf = pf.replace(include_anchor, include_anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\nextern int susfs_get_non_sus_mnt_id_from_mnt(struct mount *orig_mnt);\n#endif\n", 1)
if "struct mount *mnt = NULL;" not in pf:
    task_anchor = "\tstruct task_struct *task;\n"
    if pf.count(task_anchor) != 1:
        raise SystemExit("proc/fd.c mount variable anchor mismatch")
    pf = pf.replace(task_anchor, task_anchor + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n\tstruct mount *mnt = NULL;\n#endif\n", 1)

old_print = '\t\tseq_printf(m, "pos:\\t%lli\\nflags:\\t0%o\\nmnt_id:\\t%i\\n",\n\t\t\t   (long long)file->f_pos, f_flags,\n\t\t\t   real_mount(file->f_path.mnt)->mnt_id);'
new_print = """#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
\t\tmnt = real_mount(file->f_path.mnt);
\t\tif (mnt->mnt_id >= DEFAULT_KSU_MNT_ID && likely(susfs_is_current_proc_umounted())) {
\t\t\tstruct path path;
\t\t\tchar *pathname = kmalloc(PAGE_SIZE, GFP_KERNEL);
\t\t\tif (!pathname) {
\t\t\t\tgoto orig_flow;
\t\t\t}
\t\t\t{
\t\t\t\tchar *dpath = d_path(&file->f_path, pathname, PAGE_SIZE);
\t\t\t\tif (IS_ERR_OR_NULL(dpath) || kern_path(dpath, 0, &path)) {
\t\t\t\t\tkfree(pathname);
\t\t\t\t\tgoto orig_flow;
\t\t\t\t}
\t\t\t}
\t\t\tif (!path.dentry->d_inode) {
\t\t\t\tpath_put(&path);
\t\t\t\tkfree(pathname);
\t\t\t\tgoto orig_flow;
\t\t\t}
\t\t\tseq_printf(m, "pos:\\\\t%lli\\\\nflags:\\\\t0%o\\\\nmnt_id:\\\\t%i\\\\nino:\\\\t%lu\\\\n",
\t\t\t\t(long long)file->f_pos, f_flags,
\t\t\t\tsusfs_get_non_sus_mnt_id_from_mnt(mnt),
\t\t\t\tpath.dentry->d_inode->i_ino);
\t\t\tpath_put(&path);
\t\t\tkfree(pathname);
\t\t\tgoto bypass_orig_flow;
\t\t}
orig_flow:
\t\tseq_printf(m, "pos:\\\\t%lli\\\\nflags:\\\\t0%o\\\\nmnt_id:\\\\t%i\\\\nino:\\\\t%lu\\\\n",
\t\t\t(long long)file->f_pos, f_flags,
\t\t\treal_mount(file->f_path.mnt)->mnt_id, file_inode(file)->i_ino);
bypass_orig_flow:
#else
""" + old_print + """
#endif"""
if "susfs_get_non_sus_mnt_id_from_mnt(mnt)" not in pf:
    if pf.count(old_print) != 1:
        raise SystemExit("proc/fd.c seq_show output anchor mismatch")
    pf = pf.replace(old_print, new_print, 1)
procfd_path.write_text(pf)


# Experimental Linux 3.18 OPEN_REDIRECT port. Keep this on a separate branch
# until the target device passes openat, relative-path, fdinfo, maps and readlink tests.
# The 3.18 path_openat() API differs from the 4.4 patch; pre-resolve the requested
# pathname with filename_lookup(), then retry the normal open on the redirected name.
np = root / "fs/namei.c"
ns = np.read_text()
if "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>" not in ns:
    include_anchor = "#include <linux/init_task.h>\n"
    if ns.count(include_anchor) != 1:
        raise SystemExit("namei.c OPEN_REDIRECT include anchor mismatch")
    ns = ns.replace(include_anchor, include_anchor + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n#endif\n", 1)
if "susfs_open_redirect_spoof_do_sys_openat" not in ns:
    anchor = '#include "mount.h"\n'
    if ns.count(anchor) != 1:
        raise SystemExit("namei.c OPEN_REDIRECT prototype anchor mismatch")
    ns = ns.replace(anchor, anchor + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode);\n#endif\n", 1)
do_filp_anchor = """\tstruct nameidata nd;
\tint flags = op->lookup_flags;
\tstruct file *filp;

\tfilp = path_openat(dfd, pathname, &nd, op, flags | LOOKUP_RCU);"""
do_filp_replacement = """\tstruct nameidata nd;
\tint flags = op->lookup_flags;
\tstruct file *filp;
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tstruct filename *redirected_name = NULL;
\tstruct filename *open_name = pathname;
\tstruct nameidata check_nd;
\tunsigned int check_flags = flags & ~(LOOKUP_OPEN | LOOKUP_CREATE | LOOKUP_EXCL | LOOKUP_PARENT);

\t/*
\t * Resolve once using the caller's dfd so relative openat() paths are
\t * handled correctly. filename_lookup() returns a referenced final path;
\t * the normal open path below still performs the authoritative permission
\t * and open-flag checks.
\t */
\tif (!filename_lookup(dfd, pathname, check_flags, &check_nd)) {
\t\tstruct inode *inode = check_nd.path.dentry ? check_nd.path.dentry->d_inode : NULL;
\t\tif (inode && SUSFS_IS_INODE_OPEN_REDIRECT_WITHOUT_UID_CHECK(inode))
\t\t\tredirected_name = susfs_open_redirect_spoof_do_sys_openat(inode);
\t\tpath_put(&check_nd.path);
\t}
\tif (redirected_name && !IS_ERR(redirected_name))
\t\topen_name = redirected_name;
\telse
\t\tredirected_name = NULL;
#endif

\tfilp = path_openat(dfd, open_name, &nd, op, flags | LOOKUP_RCU);"""
if "struct filename *redirected_name = NULL;" not in ns:
    if ns.count(do_filp_anchor) != 1:
        raise SystemExit("do_filp_open OPEN_REDIRECT insertion anchor mismatch")
    ns = ns.replace(do_filp_anchor, do_filp_replacement, 1)
    # Retry with the same redirected name for -ECHILD and -ESTALE; release after all attempts.
    ns = ns.replace("filp = path_openat(dfd, pathname, &nd, op, flags);",
                    "filp = path_openat(dfd, open_name, &nd, op, flags);", 1)
    ns = ns.replace("filp = path_openat(dfd, pathname, &nd, op, flags | LOOKUP_REVAL);",
                    "filp = path_openat(dfd, open_name, &nd, op, flags | LOOKUP_REVAL);", 1)
    ret_anchor = "\treturn filp;\n}\n\nstruct file *do_file_open_root"
    ret_replacement = """#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (redirected_name)
\t\tputname(redirected_name);
#endif
\treturn filp;
}

struct file *do_file_open_root"""
    if ns.count(ret_anchor) != 1:
        raise SystemExit("do_filp_open OPEN_REDIRECT cleanup anchor mismatch")
    ns = ns.replace(ret_anchor, ret_replacement, 1)

# Reverse disguise for direct generic_readlink() calls on redirected symlink inodes.
if "susfs_open_redirect_spoof_vfs_readlink" not in ns:
    proto_anchor = "EXPORT_SYMBOL(readlink_copy);\n"
    proto = """EXPORT_SYMBOL(readlink_copy);
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
extern int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen);
#endif
"""
    if ns.count(proto_anchor) != 1:
        raise SystemExit("namei.c generic_readlink prototype anchor mismatch")
    ns = ns.replace(proto_anchor, proto, 1)
readlink_call_anchor = """\tres = readlink_copy(buffer, buflen, nd_get_link(&nd));
\tif (dentry->d_inode->i_op->put_link)"""
readlink_call_replacement = """#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (SUSFS_IS_INODE_OPEN_REDIRECT(dentry->d_inode)) {
\t\tres = susfs_open_redirect_spoof_vfs_readlink(dentry->d_inode, buffer, buflen);
\t\tif (!res) {
\t\t\tif (dentry->d_inode->i_op->put_link)
\t\t\t\tdentry->d_inode->i_op->put_link(dentry, &nd, cookie);
\t\t\treturn res;
\t\t}
\t}
#endif
\tres = readlink_copy(buffer, buflen, nd_get_link(&nd));
\tif (dentry->d_inode->i_op->put_link)"""
if "susfs_open_redirect_spoof_vfs_readlink(dentry->d_inode, buffer, buflen)" not in ns:
    if ns.count(readlink_call_anchor) != 1:
        raise SystemExit("namei.c generic_readlink insertion anchor mismatch")
    ns = ns.replace(readlink_call_anchor, readlink_call_replacement, 1)
np.write_text(ns)

# Reverse disguise for readlink("/proc/<pid>/fd/*", exe, cwd and root).
bp = root / "fs/proc/base.c"
bs = bp.read_text()
if "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>" not in bs:
    inc = "#include <linux/cpufreq_times.h>\n"
    if bs.count(inc) != 1:
        raise SystemExit("proc/base.c OPEN_REDIRECT include anchor mismatch")
    bs = bs.replace(inc, inc + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n#endif\n", 1)
if "susfs_open_redirect_spoof_do_proc_readlink" not in bs:
    anchor = "static int do_proc_readlink(struct path *path, char __user *buffer, int buflen)\n"
    proto = "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);\n#endif\n\n"
    if bs.count(anchor) != 1:
        raise SystemExit("proc/base.c readlink prototype anchor mismatch")
    bs = bs.replace(anchor, proto + anchor, 1)
readlink_anchor = """\tif (!tmp)
\t\treturn -ENOMEM;

\tpathname = d_path(path, tmp, PAGE_SIZE);"""
readlink_replacement = """\tif (!tmp)
\t\treturn -ENOMEM;

#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (SUSFS_IS_INODE_OPEN_REDIRECT(path->dentry->d_inode) &&
\t    !susfs_open_redirect_spoof_do_proc_readlink(path->dentry->d_inode, tmp, buflen)) {
\t\tlen = strlen(tmp);
\t\tif (len > buflen)
\t\t\tlen = buflen;
\t\tif (copy_to_user(buffer, tmp, len))
\t\t\tlen = -EFAULT;
\t\tgoto out;
\t}
#endif
\tpathname = d_path(path, tmp, PAGE_SIZE);"""
if "susfs_open_redirect_spoof_do_proc_readlink(path->dentry->d_inode, tmp, buflen)" not in bs:
    if bs.count(readlink_anchor) != 1:
        raise SystemExit("proc/base.c readlink insertion anchor mismatch")
    bs = bs.replace(readlink_anchor, readlink_replacement, 1)
bp.write_text(bs)

# Reverse disguise for fdinfo (mnt_id + inode number).
pf_path = root / "fs/proc/fd.c"
pf = pf_path.read_text()
if "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>" not in pf:
    inc = "#include <linux/proc_fs.h>\n"
    if pf.count(inc) != 1:
        raise SystemExit("proc/fd.c OPEN_REDIRECT include anchor mismatch")
    pf = pf.replace(inc, inc + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n#endif\n", 1)
if "susfs_open_redirect_spoof_seq_show" not in pf:
    anchor = '#include "fd.h"\n'
    proto = '#include "fd.h"\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern int susfs_open_redirect_spoof_seq_show(struct inode *inode, int *out_mnt_id, unsigned long *out_ino);\n#endif\n'
    if pf.count(anchor) != 1:
        raise SystemExit("proc/fd.c OPEN_REDIRECT prototype anchor mismatch")
    pf = pf.replace(anchor, proto, 1)
fd_print_anchor = """\t\tseq_printf(m, "pos:\\\\t%lli\\\\nflags:\\\\t0%o\\\\nmnt_id:\\\\t%i\\\\nino:\\\\t%lu\\\\n",
\t\t\t(long long)file->f_pos, f_flags,
\t\t\treal_mount(file->f_path.mnt)->mnt_id, file_inode(file)->i_ino);
bypass_orig_flow:"""
fd_print_replacement = """#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\t\tif (SUSFS_IS_INODE_OPEN_REDIRECT(file_inode(file))) {
\t\t\tint spoofed_mnt_id = 0;
\t\t\tunsigned long spoofed_ino = 0;
\t\t\tif (!susfs_open_redirect_spoof_seq_show(file_inode(file), &spoofed_mnt_id, &spoofed_ino)) {
\t\t\t\tseq_printf(m, "pos:\\\\t%lli\\\\nflags:\\\\t0%o\\\\nmnt_id:\\\\t%i\\\\nino:\\\\t%lu\\\\n",
\t\t\t\t\t(long long)file->f_pos, f_flags, spoofed_mnt_id, spoofed_ino);
\t\t\t\tgoto bypass_orig_flow;
\t\t\t}
\t\t}
#endif
\t\tseq_printf(m, "pos:\\\\t%lli\\\\nflags:\\\\t0%o\\\\nmnt_id:\\\\t%i\\\\nino:\\\\t%lu\\\\n",
\t\t\t(long long)file->f_pos, f_flags,
\t\t\treal_mount(file->f_path.mnt)->mnt_id, file_inode(file)->i_ino);
bypass_orig_flow:"""
if "susfs_open_redirect_spoof_seq_show(file_inode(file)" not in pf:
    if pf.count(fd_print_anchor) != 1:
        raise SystemExit("proc/fd.c fdinfo reverse-spoof anchor mismatch")
    pf = pf.replace(fd_print_anchor, fd_print_replacement, 1)
pf_path.write_text(pf)

# Reverse disguise in /proc/<pid>/maps, preserving SRCU protection while the
# spoofed pathname is emitted from the rule table.
mm_path = root / "fs/proc/task_mmu.c"
mm = mm_path.read_text()
if "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>" not in mm:
    inc = "#include <linux/mm_inline.h>\n"
    if mm.count(inc) != 1:
        raise SystemExit("task_mmu.c OPEN_REDIRECT include anchor mismatch")
    mm = mm.replace(inc, inc + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n#include <linux/srcu.h>\n#endif\n", 1)
if "susfs_open_redirect_spoof_show_map_vma_srcu" not in mm:
    anchor = "static void\nshow_map_vma(struct seq_file *m, struct vm_area_struct *vma, int is_pid)\n"
    proto = """#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
extern struct srcu_struct susfs_srcu_open_redirect;
extern int susfs_open_redirect_spoof_show_map_vma_srcu(struct inode *inode, unsigned long *out_ino, dev_t *out_dev, char **out_spoofed_name);
#endif

"""
    if mm.count(anchor) != 1:
        raise SystemExit("task_mmu.c show_map_vma prototype anchor mismatch")
    mm = mm.replace(anchor, proto + anchor, 1)
map_anchor = """\tif (file) {
\t\tstruct inode *inode = file_inode(vma->vm_file);
"""
map_replacement = """\tif (file) {
\t\tstruct inode *inode = file_inode(vma->vm_file);
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\t\tif (SUSFS_IS_INODE_OPEN_REDIRECT(inode)) {
\t\t\tchar *spoofed_name = NULL;
\t\t\tint srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
\t\t\tif (!susfs_open_redirect_spoof_show_map_vma_srcu(inode, &ino, &dev, &spoofed_name)) {
\t\t\t\tpgoff = ((loff_t)vma->vm_pgoff) << PAGE_SHIFT;
\t\t\t\tstart = vma->vm_start;
\t\t\t\tend = vma->vm_end;
\t\t\t\tshow_vma_header_prefix(m, start, end, flags, pgoff, dev, ino);
\t\t\t\tseq_pad(m, ' ');
\t\t\t\tif (spoofed_name)
\t\t\t\t\tseq_puts(m, spoofed_name);
\t\t\t\tseq_putc(m, '\\\\n');
\t\t\t\tsrcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
\t\t\t\treturn;
\t\t\t}
\t\t\tsrcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
\t\t}
#endif
"""
if "susfs_open_redirect_spoof_show_map_vma_srcu(inode" not in mm:
    if mm.count(map_anchor) != 1:
        raise SystemExit("task_mmu.c maps reverse-spoof anchor mismatch")
    mm = mm.replace(map_anchor, map_replacement, 1)
mm_path.write_text(mm)

# Return the target filesystem's statfs snapshot for a redirected inode.
sp = root / "fs/statfs.c"
st = sp.read_text()
if "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>" not in st:
    inc = "#include <linux/uaccess.h>\n"
    if st.count(inc) != 1:
        raise SystemExit("statfs.c OPEN_REDIRECT include anchor mismatch")
    st = st.replace(inc, inc + "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n#endif\n", 1)
if "susfs_open_redirect_spoof_vfs_statfs" not in st:
    anchor = "int vfs_statfs(struct path *path, struct kstatfs *buf)\n"
    proto = "#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf);\n#endif\n\n"
    if st.count(anchor) != 1:
        raise SystemExit("statfs.c OPEN_REDIRECT prototype anchor mismatch")
    st = st.replace(anchor, proto + anchor, 1)
stat_anchor = """int vfs_statfs(struct path *path, struct kstatfs *buf)
{
\tint error;

\terror = statfs_by_dentry(path->dentry, buf);"""
stat_replacement = """int vfs_statfs(struct path *path, struct kstatfs *buf)
{
\tint error;
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (path->dentry && path->dentry->d_inode &&
\t    SUSFS_IS_INODE_OPEN_REDIRECT(path->dentry->d_inode) &&
\t    !susfs_open_redirect_spoof_vfs_statfs(path->dentry->d_inode, buf))
\t\treturn 0;
#endif
\terror = statfs_by_dentry(path->dentry, buf);"""
if "susfs_open_redirect_spoof_vfs_statfs(path->dentry->d_inode, buf)" not in st:
    if st.count(stat_anchor) != 1:
        raise SystemExit("statfs.c reverse-spoof insertion anchor mismatch")
    st = st.replace(stat_anchor, stat_replacement, 1)
sp.write_text(st)

# Preserve every rejected hunk verbatim, then remove only the allowlisted
# .rej files because the candidate profile explicitly disables those features.
manifest = []
for rel, reason in deferred.items():
    src = found[rel]
    dst = deferred_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if rel == "fs/namei.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_PATH code adapted for Linux 3.18; enabled only in staged candidate build")
    elif rel == "fs/readdir.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_PATH fillonedir code adapted for Linux 3.18; enabled only in staged candidate build")
    elif rel == "fs/namespace.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_MOUNT namespace declarations adapted for Linux 3.18")
    elif rel == "fs/notify/fdinfo.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_MOUNT fdinfo code adapted for Linux 3.18; enabled only in staged candidate build")
    elif rel == "fs/proc/fd.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_MOUNT proc-fd code adapted for Linux 3.18; enabled only in staged candidate build")
    elif rel == "fs/proc/task_mmu.c.rej":
        manifest.append(f"{rel}\tPARTIALLY_ADAPTED\tSUS_MAP code adapted for Linux 3.18; enabled only in staged candidate build")
    else:
        manifest.append(f"{rel}\tDEFERRED\t{reason}")
    src.unlink()

avc_rej = found.get("security/selinux/avc.c.rej")
if avc_rej:
    dst = deferred_dir / "security/selinux/avc.c.rej"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(avc_rej, dst)
    avc_rej.unlink()
    manifest.append("security/selinux/avc.c.rej\tMANUALLY_ADAPTED\tAdded required bypass_orig_flow label at the 3.18 AVC flow")

# In this candidate SUSFS is a feature layer, not the selected inline-hook method.
# When Manual Hook and SUSFS are both enabled, prefer the Manual Hook branch in
# ksud_integration.c; otherwise AUTO_INITRC references ksu_init_rc_hook while the
# SUSFS branch defines ksu_is_init_rc_hook_enabled, causing an undefined symbol.
runtime_path = root / "drivers/kernelsu/runtime/ksud_integration.c"
runtime_text = runtime_path.read_text()
runtime_lines = runtime_text.splitlines()
legacy_branch = "#elif defined(CONFIG_KSU_SUSFS)"
manual_safe_branch = "#elif defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_KSU_MANUAL_HOOK)"
legacy_indexes = [i for i, line in enumerate(runtime_lines) if line.strip() == legacy_branch]
safe_indexes = [i for i, line in enumerate(runtime_lines) if line.strip() == manual_safe_branch]
if len(legacy_indexes) == 1 and not safe_indexes:
    runtime_lines[legacy_indexes[0]] = runtime_lines[legacy_indexes[0]] + " && !defined(CONFIG_KSU_MANUAL_HOOK)"
elif not legacy_indexes and len(safe_indexes) == 1:
    pass  # Idempotent: the intended branch guard is already present.
else:
    print(f"runtime path: {runtime_path}; resolved: {runtime_path.resolve()}")
    print(f"SUSFS branch counts: legacy={len(legacy_indexes)}, guarded={len(safe_indexes)}")
    print("Conditional/initrc lines in runtime source:")
    for line_no, line in enumerate(runtime_lines, 1):
        if "#elif" in line or "init_rc" in line or "ksu_is_" in line:
            print(f"{line_no}: {line}")
    (artifacts / "runtime-initrc-hook-source.c").write_text(runtime_text)
    raise SystemExit("Could not uniquely identify SUSFS runtime branch for Manual Hook precedence; diagnostic source uploaded")
runtime_text = "\n".join(runtime_lines) + ("\n" if runtime_text.endswith("\n") else "")
runtime_path.write_text(runtime_text)

# Normalize only whitespace artifacts introduced by the pinned patch/script.
ns = root / "fs/namespace.c"
ns_data = ns.read_text()
ns.write_text(ns_data.rstrip() + "\n")
rw = root / "fs/read_write.c"
rw_lines = rw.read_text().splitlines()
rw.write_text("\n".join(line.rstrip() if not line.strip() else line for line in rw_lines) + "\n")
seccomp = root / "include/linux/seccomp.h"
seccomp_text = seccomp.read_text()
seccomp_text = seccomp_text.replace("\n \tatomic_t filter_count;", "\n\tatomic_t filter_count;")
seccomp.write_text(seccomp_text)

(artifacts / "deferred-feature-contract.txt").write_text(
    "SUSFS v2.2 Linux 3.18 experimental compatibility profile — SUS_PATH, SUS_MOUNT, SUS_KSTAT and SUS_MAP are enabled after compatibility adaptations; OPEN_REDIRECT is enabled experimentally with Linux 3.18 openat, proc-readlink, fdinfo, maps and statfs adapters. Build success is not runtime/boot validation.\n"
    "KSU_SUSFS_SUS_PATH=y\n"
    "KSU_SUSFS_SUS_MOUNT=y\n"
    "KSU_SUSFS_SUS_KSTAT=y\n"
    "KSU_SUSFS_OPEN_REDIRECT=y\n"
    "KSU_SUSFS_SUS_MAP=y\n"
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
