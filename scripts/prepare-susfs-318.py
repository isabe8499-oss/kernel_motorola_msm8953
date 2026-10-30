#!/usr/bin/env python3
"""Stage the pinned SUSFS 2.2.0 core and apply only Linux 3.18 API shims.

This does not enable CONFIG_KSU_SUSFS and does not claim that the VFS/proc/mm
feature hooks are complete. It makes the exact core source available for the
next porting/build stage.
"""
from pathlib import Path
import re
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

def patch_no_su_helpers(path):
    content = read(path)
    helper_names = (
        "susfs_is_current_proc_no_su",
        "susfs_set_current_proc_no_su",
        "susfs_clear_current_proc_no_su",
    )
    counts = {name: content.count(name) for name in helper_names}
    if all(count == 1 for count in counts.values()):
        return
    if any(count for count in counts.values()):
        raise SystemExit(f"Partial BakaSU no-su helper set already present: {counts}")

    # Match the actual pinned upstream helper independent of tabs/spaces and
    # CRLF/LF. Limit the match to this small function body, not the whole header.
    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)static inline void "
        r"susfs_set_current_proc_umounted\s*\(\s*void\s*\)\s*\{"
        r"\s*(?P<body>[ \t]*set_thread_flag\s*\(\s*TIF_PROC_UMOUNTED\s*\)\s*;\s*)\}"
    )
    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        preview = repr(content[content.find("susfs_set_current_proc_umounted") - 48:
                               content.find("susfs_set_current_proc_umounted") + 180])
        raise SystemExit(
            "BakaSU no-su helper insertion: expected one upstream "
            "susfs_set_current_proc_umounted function; "
            f"found={len(matches)}; source={preview}"
        )

    match = matches[0]
    indent = match.group("indent")
    helper_block = (
        match.group(0)
        + "\n"
        + indent + "static inline bool susfs_is_current_proc_no_su(void) {\n"
        + indent + "\treturn likely(test_thread_flag(TIF_PROC_NO_SU));\n"
        + indent + "}\n"
        + indent + "static inline void susfs_set_current_proc_no_su(void) {\n"
        + indent + "\tset_thread_flag(TIF_PROC_NO_SU);\n"
        + indent + "}\n"
        + indent + "static inline void susfs_clear_current_proc_no_su(void) {\n"
        + indent + "\tclear_thread_flag(TIF_PROC_NO_SU);\n"
        + indent + "}\n"
    )
    content = content[:match.start()] + helper_block + content[match.end():]
    if any(content.count(name) != 1 for name in helper_names):
        raise SystemExit("BakaSU no-su helper insertion did not produce exactly one of each helper")
    write(path, content)

patch_no_su_helpers(def_path)

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

# SUSFS v2.2.0 has a bitmask typo: (1 < 8) evaluates to bit 0, not bit 8.
replace_once(
    ROOT / "include/linux/susfs.h",
    "#define KSTAT_SPOOF_CTIME_TV_SEC (1 < 8)",
    "#define KSTAT_SPOOF_CTIME_TV_SEC (1 << 8)",
    "SUSFS kstat ctime flag bit",
)

# The upstream show_map helper allocates spoofed_name but takes char * by
# value, so the caller can never receive that allocation. Make it an explicit
# output parameter before wiring the proc maps consumer.
replace_once(
    susfs_c,
    "int susfs_open_redirect_spoof_show_map_vma(struct inode *inode, unsigned long *out_ino, dev_t *out_dev, char *spoofed_name) {",
    "int susfs_open_redirect_spoof_show_map_vma(struct inode *inode, unsigned long *out_ino, dev_t *out_dev, char **spoofed_name) {",
    "SUSFS open redirect maps output pointer",
)
replace_once(
    susfs_c,
    "\tif (spoofed_name) {\n\t\tSUSFS_LOGE(\"spoofed_name must be NULL first!\\n\");\n\t\treturn -EINVAL;\n\t}",
    "\tif (!spoofed_name || *spoofed_name) {\n\t\tSUSFS_LOGE(\"spoofed_name output must point to NULL!\\n\");\n\t\treturn -EINVAL;\n\t}",
    "SUSFS open redirect maps output validation",
)
replace_once(
    susfs_c,
    "\t\t\tspoofed_name = kzalloc(SUSFS_MAX_LEN_PATHNAME, GFP_KERNEL);\n\t\t\tif (!spoofed_name) {",
    "\t\t\t*spoofed_name = kzalloc(SUSFS_MAX_LEN_PATHNAME, GFP_KERNEL);\n\t\t\tif (!*spoofed_name) {",
    "SUSFS open redirect maps output allocation",
)


replace_once(
    susfs_c,
    "strscpy(spoofed_name, entry->info.redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);",
    "strscpy(*spoofed_name, entry->info.redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);",
    "SUSFS open redirect maps output copy",
)

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


# Linux 3.18 directory callbacks use the legacy void * callback ABI. Resolve
# each emitted inode against the directory superblock and hide SUS_PATH inodes.
readdir = ROOT / "fs/readdir.c"
replace_once(
    readdir,
    "#include <linux/unistd.h>\n",
    """#include <linux/unistd.h>
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
#include <linux/susfs_def.h>
extern int susfs_get_data_path(struct path *path);
extern bool susfs_is_inode_sus_path(struct inode *inode);
#endif
""",
    "SUSFS readdir declarations",
)
replace_once(
    readdir,
    "static bool hide_name(const char *name, int namlen)\n",
    """#ifdef CONFIG_KSU_SUSFS_SUS_PATH
static inline struct super_block *
susfs_readdir_get_sb(struct file *file, struct path *data_path, int *path_err)
{
    struct super_block *sb = file->f_inode->i_sb;

    *path_err = -EINVAL;
    if (sb->s_magic == FUSE_SUPER_MAGIC) {
        *path_err = susfs_get_data_path(data_path);
        if (!*path_err && data_path->dentry && data_path->dentry->d_inode)
            return data_path->dentry->d_inode->i_sb;
        if (!*path_err)
            *path_err = -ENOENT;
    }
    return sb;
}

static inline bool susfs_is_hidden_dirent(struct super_block *sb, u64 ino)
{
    struct inode *inode;
    bool hidden;

    if (!sb)
        return false;
    inode = ilookup(sb, (unsigned long)ino);
    if (!inode)
        return false;
    hidden = susfs_is_inode_sus_path(inode);
    iput(inode);
    return hidden;
}
#endif

static bool hide_name(const char *name, int namlen)
""",
    "SUSFS readdir helpers",
)
replace_once(
    readdir,
    "struct readdir_callback {\n\tstruct dir_context ctx;\n\tstruct old_linux_dirent __user * dirent;\n\tint result;\n};",
    """struct readdir_callback {
\tstruct dir_context ctx;
\tstruct old_linux_dirent __user * dirent;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tstruct super_block *sb;
#endif
\tint result;
};""",
    "old_readdir callback superblock",
)
replace_once(
    readdir,
    "struct getdents_callback {\n\tstruct dir_context ctx;\n\tstruct linux_dirent __user * current_dir;\n\tstruct linux_dirent __user * previous;\n\tint count;\n\tint error;\n};",
    """struct getdents_callback {
\tstruct dir_context ctx;
\tstruct linux_dirent __user * current_dir;
\tstruct linux_dirent __user * previous;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tstruct super_block *sb;
#endif
\tint count;
\tint error;
};""",
    "getdents callback superblock",
)
replace_once(
    readdir,
    "struct getdents_callback64 {\n\tstruct dir_context ctx;\n\tstruct linux_dirent64 __user * current_dir;\n\tstruct linux_dirent64 __user * previous;\n\tint count;\n\tint error;\n};",
    """struct getdents_callback64 {
\tstruct dir_context ctx;
\tstruct linux_dirent64 __user * current_dir;
\tstruct linux_dirent64 __user * previous;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tstruct super_block *sb;
#endif
\tint count;
\tint error;
};""",
    "getdents64 callback superblock",
)

# Add inode lookup to the legacy filldir callbacks. The inode reference is
# released on both paths before returning to the filesystem iterator.
replace_once(
    readdir,
    "\tunsigned long d_ino;\n\n\tif (buf->result)",
    "\tunsigned long d_ino;\n\n\tif (buf->result)",
    "old_readdir overflow anchor",
)
replace_once(
    readdir,
    "\tif (sizeof(d_ino) < sizeof(ino) && d_ino != ino) {\n\t\tbuf->result = -EOVERFLOW;\n\t\treturn -EOVERFLOW;\n\t}\n\tif (hide_name(name, namlen) && buf->ctx.romnt)",
    """\tif (sizeof(d_ino) < sizeof(ino) && d_ino != ino) {
\t\tbuf->result = -EOVERFLOW;
\t\treturn -EOVERFLOW;
\t}
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (susfs_is_hidden_dirent(buf->sb, ino))
\t\treturn 0;
#endif
\tif (hide_name(name, namlen) && buf->ctx.romnt)""",
    "old_readdir SUS_PATH filtering",
)
replace_once(
    readdir,
    "\t\tif (!f.file)\n\t\t\treturn -EBADF;",
    "\t\tif (!f.file)\n\t\t\treturn -EBADF;",
    "old_readdir descriptor anchor",
)
replace_once(
    readdir,
    """\tstruct readdir_callback buf = {
\t\t.ctx.actor = fillonedir,
\t\t.dirent = dirent
\t};

\tif (!f.file)
\t\treturn -EBADF;

\terror = iterate_dir(f.file, &buf.ctx);""",
    """\tstruct readdir_callback buf = {
\t\t.ctx.actor = fillonedir,
\t\t.dirent = dirent
\t};
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tint path_err = -EINVAL;
\tstruct path data_path;
#endif

\tif (!f.file)
\t\treturn -EBADF;

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tbuf.sb = susfs_readdir_get_sb(f.file, &data_path, &path_err);
#endif
\terror = iterate_dir(f.file, &buf.ctx);""",
    "old_readdir superblock selection",
)
replace_once(
    readdir,
    """\tfdput(f);
\treturn error;
}

#endif /* __ARCH_WANT_OLD_READDIR */""",
    """\tfdput(f);
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (!path_err)
\t\tpath_put(&data_path);
#endif
\treturn error;
}

#endif /* __ARCH_WANT_OLD_READDIR */""",
    "old_readdir FUSE data path release",
)

replace_once(
    readdir,
    "\tunsigned long d_ino;\n\tint reclen = ALIGN(offsetof(struct linux_dirent, d_name) + namlen + 2,",
    "\tunsigned long d_ino;\n\tint reclen = ALIGN(offsetof(struct linux_dirent, d_name) + namlen + 2,",
    "getdents filldir declaration",
)
replace_once(
    readdir,
    """\tif (sizeof(d_ino) < sizeof(ino) && d_ino != ino) {
\t\tbuf->error = -EOVERFLOW;
\t\treturn -EOVERFLOW;
\t}
\tif (hide_name(name, namlen) && buf->ctx.romnt)""",
    """\tif (sizeof(d_ino) < sizeof(ino) && d_ino != ino) {
\t\tbuf->error = -EOVERFLOW;
\t\treturn -EOVERFLOW;
\t}
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (susfs_is_hidden_dirent(buf->sb, ino))
\t\treturn 0;
#endif
\tif (hide_name(name, namlen) && buf->ctx.romnt)""",
    "getdents SUS_PATH filtering",
)
replace_once(
    readdir,
    """\t};
\tint error;

\tif (!access_ok(VERIFY_WRITE, dirent, count))
\t\treturn -EFAULT;

\tf = fdget(fd);
\tif (!f.file)
\t\treturn -EBADF;

\terror = iterate_dir(f.file, &buf.ctx);""",
    """\t};
\tint error;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tint path_err = -EINVAL;
\tstruct path data_path;
#endif

\tif (!access_ok(VERIFY_WRITE, dirent, count))
\t\treturn -EFAULT;

\tf = fdget(fd);
\tif (!f.file)
\t\treturn -EBADF;

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tbuf.sb = susfs_readdir_get_sb(f.file, &data_path, &path_err);
#endif
\terror = iterate_dir(f.file, &buf.ctx);""",
    "getdents superblock selection",
)
replace_once(
    readdir,
    """\tfdput(f);
\treturn error;
}

struct getdents_callback64""",
    """\tfdput(f);
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (!path_err)
\t\tpath_put(&data_path);
#endif
\treturn error;
}

struct getdents_callback64""",
    "getdents FUSE data path release",
)
replace_once(
    readdir,
    """\tif (reclen > buf->count)
\t\treturn -EINVAL;
\tif (hide_name(name, namlen) && buf->ctx.romnt)""",
    """\tif (reclen > buf->count)
\t\treturn -EINVAL;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (susfs_is_hidden_dirent(buf->sb, ino))
\t\treturn 0;
#endif
\tif (hide_name(name, namlen) && buf->ctx.romnt)""",
    "getdents64 SUS_PATH filtering",
)
replace_once(
    readdir,
    """\t};
\tint error;

\tif (!access_ok(VERIFY_WRITE, dirent, count))
\t\treturn -EFAULT;

\tf = fdget(fd);
\tif (!f.file)
\t\treturn -EBADF;

\terror = iterate_dir(f.file, &buf.ctx);""",
    """\t};
\tint error;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tint path_err = -EINVAL;
\tstruct path data_path;
#endif

\tif (!access_ok(VERIFY_WRITE, dirent, count))
\t\treturn -EFAULT;

\tf = fdget(fd);
\tif (!f.file)
\t\treturn -EBADF;

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tbuf.sb = susfs_readdir_get_sb(f.file, &data_path, &path_err);
#endif
\terror = iterate_dir(f.file, &buf.ctx);""",
    "getdents64 superblock selection",
)
replace_once(
    readdir,
    """\tfdput(f);
\treturn error;
}""",
    """\tfdput(f);
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tif (!path_err)
\t\tpath_put(&data_path);
#endif
\treturn error;
}""",
    "getdents64 FUSE data path release",
)

if "susfs_is_hidden_dirent(buf->sb, ino)" not in read(readdir):
    raise SystemExit("SUSFS readdir inode filter was not staged")
if "susfs_readdir_get_sb(f.file, &data_path, &path_err)" not in read(readdir):
    raise SystemExit("SUSFS FUSE readdir superblock resolver was not staged")

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
if "char **spoofed_name" not in read(susfs_c):
    raise SystemExit("SUSFS open redirect maps output parameter was not repaired")
if "#define KSTAT_SPOOF_CTIME_TV_SEC (1 << 8)" not in read(ROOT / "include/linux/susfs.h"):
    raise SystemExit("SUSFS kstat ctime flag fix missing")
if "susfs_is_current_proc_no_su" not in read(def_path):
    raise SystemExit("BakaSU UAPI 6 no-su helper missing")
if object_line not in read(makefile):
    raise SystemExit("fs/Makefile does not link susfs.o")

print("SUSFS v2.2.0 core staged with Linux 3.18 static-key/fsnotify shims.")
print("CONFIG_KSU_SUSFS remains disabled; VFS/proc/mm feature hooks are not yet complete.")
