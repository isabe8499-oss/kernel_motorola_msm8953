#!/usr/bin/env python3
"""Stage the pinned SUSFS 2.2.0 core and apply only Linux 3.18 API shims.

This does not enable CONFIG_KSU_SUSFS and does not claim that the VFS/proc/mm
feature hooks are complete. It makes the exact core source available for the
next porting/build stage.
"""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(".")
SUSFS = ROOT / "SUSFS"
EXPECTED = "4003ecf2d01c6d13fa8edf6c4f2607365738dc3d"

actual = subprocess.check_output(
    ["git", "-C", str(SUSFS), "rev-parse", "HEAD"], text=True
).strip()
if actual != EXPECTED:
    raise SystemExit(f"Unexpected SUSFS source: {actual}")

source_files = {
    SUSFS / "kernel_patches/fs/susfs.c": ROOT / "fs/susfs.c",
    SUSFS / "kernel_patches/include/linux/susfs.h": ROOT / "include/linux/susfs.h",
    SUSFS / "kernel_patches/include/linux/susfs_def.h": ROOT / "include/linux/susfs_def.h",
}
for source, target in source_files.items():
    if not source.is_file():
        raise SystemExit(f"Missing pinned SUSFS source file: {source}")
    shutil.copyfile(source, target)

def read(path):
    return path.read_text()

def write(path, content):
    path.write_text(content)

def replace_once(path, old, new, label):
    content = read(path)
    old_count = content.count(old)
    new_count = content.count(new)
    if old_count == 1 and new_count == 0:
        write(path, content.replace(old, new, 1))
    elif old_count == 0 and new_count == 1:
        return
    else:
        raise SystemExit(
            f"{label}: expected one upstream or one patched anchor; "
            f"old={old_count}, new={new_count}"
        )

# Linux 3.18 has BIT/GENMASK in bitops.h, not linux/bits.h. The pinned
# SUSFS header is parsed structurally instead of relying on a brittle full
# multiline string (Git checkouts may differ in BOM/line-ending/blank-line form).
def_path = ROOT / "include/linux/susfs_def.h"

def patch_susfs_def_header(path):
    content = read(path).lstrip("\ufeff")
    lines = content.splitlines(keepends=True)
    guards = [i for i, line in enumerate(lines)
              if line.strip() == "#ifndef KSU_SUSFS_DEF_H"]
    if len(guards) != 1:
        preview = repr("".join(lines[:12]))
        raise SystemExit(
            "susfs_def.h: expected one KSU_SUSFS_DEF_H guard; "
            f"found={len(guards)}; header={preview}"
        )

    guard = guards[0]
    define = guard + 1
    while define < len(lines) and not lines[define].strip():
        define += 1
    if define >= len(lines) or lines[define].strip() != "#define KSU_SUSFS_DEF_H":
        raise SystemExit("susfs_def.h: KSU_SUSFS_DEF_H define does not follow its guard")

    # Consume only the leading include/blank block. Do not rewrite later
    # includes or declarations in the SUSFS UAPI header.
    end = define + 1
    include_lines = []
    while end < len(lines):
        stripped = lines[end].strip()
        if not stripped:
            end += 1
            continue
        if stripped.startswith("#include "):
            include_lines.append(stripped)
            end += 1
            continue
        break

    old_set = ["#include <linux/bits.h>", "#include <linux/string.h>"]
    new_marker = "void susfs_static_branch_enable(struct static_key *key);"
    if include_lines == old_set:
        lines = lines[:define + 1] + [new_includes] + lines[end:]
        write(path, "".join(lines))
        return
    if (include_lines == [
            "#include <linux/bitops.h>",
            "#include <linux/cred.h>",
            "#include <linux/jump_label.h>",
            "#include <linux/string.h>",
            "#include <linux/thread_info.h>",
        ] and new_marker in content):
        return

    preview = repr("".join(lines[:15]))
    raise SystemExit(
        "susfs_def.h: unexpected leading include block; "
        f"found={include_lines!r}; header={preview}"
    )

new_includes = """#include <linux/bitops.h>
#include <linux/cred.h>
#include <linux/jump_label.h>
#include <linux/string.h>
#include <linux/thread_info.h>

#ifndef DEFINE_STATIC_KEY_TRUE
#define DEFINE_STATIC_KEY_TRUE(name) struct static_key name = STATIC_KEY_INIT_TRUE
#endif
#ifndef DEFINE_STATIC_KEY_FALSE
#define DEFINE_STATIC_KEY_FALSE(name) struct static_key name = STATIC_KEY_INIT_FALSE
#endif
#ifndef static_branch_likely
#define static_branch_likely(key) static_key_true(key)
#endif
#ifndef static_branch_unlikely
#define static_branch_unlikely(key) static_key_false(key)
#endif

void susfs_static_branch_enable(struct static_key *key);
void susfs_static_branch_disable(struct static_key *key);
#ifndef static_branch_enable
#define static_branch_enable(key) susfs_static_branch_enable(key)
#endif
#ifndef static_branch_disable
#define static_branch_disable(key) susfs_static_branch_disable(key)
#endif
"""
patch_susfs_def_header(def_path)

replace_once(
    def_path,
    "#define TIF_PROC_UMOUNTED 33",
    "#define TIF_PROC_UMOUNTED 33\n#define TIF_PROC_NO_SU 34",
    "SUSFS/BakaSU no-su thread flag",
)

no_su_old = """static inline void susfs_set_current_proc_umounted(void) {
\tset_thread_flag(TIF_PROC_UMOUNTED);
}
static inline bool susfs_is_current_proc_umounted_app(void) {"""
no_su_new = """static inline void susfs_set_current_proc_umounted(void) {
\tset_thread_flag(TIF_PROC_UMOUNTED);
}
static inline bool susfs_is_current_proc_no_su(void) {
\treturn (likely(test_thread_flag(TIF_PROC_NO_SU)));
}
static inline void susfs_set_current_proc_no_su(void) {
\tset_thread_flag(TIF_PROC_NO_SU);
}
static inline void susfs_clear_current_proc_no_su(void) {
\tclear_thread_flag(TIF_PROC_NO_SU);
}
static inline bool susfs_is_current_proc_umounted_app(void) {"""
replace_once(def_path, no_su_old, no_su_new, "BakaSU UAPI 6 no-su process helpers")

# Linux 3.18 static_key_slow_inc/dec are reference-counted. SUSFS 2.2 calls
# static_branch_enable/disable on repeated manager requests, so make the
# compatibility layer idempotent and serialize state transitions.
susfs_c = ROOT / "fs/susfs.c"
key_anchor = "DEFINE_STATIC_KEY_TRUE(susfs_is_log_enabled);"
key_compat = """static DEFINE_MUTEX(susfs_static_key_compat_lock);

void susfs_static_branch_enable(struct static_key *key)
{
\tmutex_lock(&susfs_static_key_compat_lock);
\tif (!static_key_enabled(key))
\t\tstatic_key_slow_inc(key);
\tmutex_unlock(&susfs_static_key_compat_lock);
}

void susfs_static_branch_disable(struct static_key *key)
{
\tmutex_lock(&susfs_static_key_compat_lock);
\tif (static_key_enabled(key))
\t\tstatic_key_slow_dec(key);
\tmutex_unlock(&susfs_static_key_compat_lock);
}

"""
replace_once(susfs_c, key_anchor, key_compat + key_anchor, "SUSFS static-key idempotent wrappers")

# 3.18 fsnotify uses handle_event(group, inode, marks, mask, data, type,
# file_name, cookie), fsnotify_init_mark(mark, free_mark), and fsnotify_add_mark.
fsnotify_old = """static const struct fsnotify_ops fsnotify_ops = {
\t.handle_inode_event = susfs_handle_sdcard_inode_event,
};"""
fsnotify_new = """static int susfs_handle_sdcard_event_compat(struct fsnotify_group *group,
\tstruct inode *inode,
\tstruct fsnotify_mark *inode_mark,
\tstruct fsnotify_mark *vfsmount_mark,
\tu32 mask, void *data, int data_type,
\tconst unsigned char *file_name, u32 cookie)
{
\tstruct qstr qname;
\tif (!file_name)
\t\treturn 0;
\tqname.name = file_name;
\tqname.len = strlen(file_name);
\treturn susfs_handle_sdcard_inode_event(inode_mark, mask, inode, NULL,
\t\t\t\t\t\t\t&qname, cookie);
}

static const struct fsnotify_ops fsnotify_ops = {
\t.handle_event = susfs_handle_sdcard_event_compat,
};"""
replace_once(susfs_c, fsnotify_old, fsnotify_new, "fsnotify handle_event compatibility")

replace_once(
    susfs_c,
    "fsnotify_init_mark(m, g);",
    "fsnotify_init_mark(m, NULL);",
    "fsnotify_init_mark legacy signature",
)
replace_once(
    susfs_c,
    "if (fsnotify_add_inode_mark(m, inode, 0)) {",
    "if (fsnotify_add_mark(m, g, inode, NULL, 0)) {",
    "fsnotify_add_mark legacy signature",
)

# The SUSFS object is linked only when the BakaSU feature is explicitly enabled.
makefile = ROOT / "fs/Makefile"
make_text = read(makefile)
object_line = "obj-$(CONFIG_KSU_SUSFS) += susfs.o"
if object_line not in make_text:
    write(makefile, make_text.rstrip() + "\n\n" + object_line + "\n")

# Fail early if the staging step did not leave the expected source/version/API.
header = read(ROOT / "include/linux/susfs.h")
if '#define SUSFS_VERSION "v2.2.0"' not in header:
    raise SystemExit("Staged SUSFS header is not v2.2.0")
if ".handle_event = susfs_handle_sdcard_event_compat" not in read(susfs_c):
    raise SystemExit("SUSFS fsnotify compatibility callback missing")
if "susfs_is_current_proc_no_su" not in read(def_path):
    raise SystemExit("BakaSU UAPI 6 no-su helper missing")
if object_line not in read(makefile):
    raise SystemExit("fs/Makefile does not link susfs.o")

print("SUSFS v2.2.0 core staged with Linux 3.18 static-key/fsnotify shims.")
print("CONFIG_KSU_SUSFS remains disabled; VFS/proc/mm feature hooks are not yet complete.")
