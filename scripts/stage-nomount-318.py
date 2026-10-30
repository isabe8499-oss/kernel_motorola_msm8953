#!/usr/bin/env python3
"""Stage NoMount v2.2.0 and apply the Linux 3.18 VFS compatibility layer.

The adapter restores the legacy iterate, follow_link and inode xattr callbacks.
CONFIG_NOMOUNT stays disabled in the device defconfig until the object and full
kernel build/runtime checks have passed.
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


def replace_once(path, old, new, label):
    content = path.read_text()
    old_count = content.count(old)
    new_count = content.count(new)
    if old_count == 1 and new_count == 0:
        path.write_text(content.replace(old, new, 1))
    elif old_count == 0 and new_count == 1:
        return
    else:
        raise SystemExit(
            f"{label}: expected one upstream or one patched anchor; "
            f"old={old_count}, new={new_count}"
        )


def wrap_region(path, start, end, opening, closing, label):
    content = path.read_text()
    if opening in content and closing in content:
        return
    if content.count(start) != 1 or content.count(end) != 1:
        raise SystemExit(f"{label}: source region is missing or ambiguous")
    first = content.index(start)
    last = content.index(end, first + len(start))
    if last <= first:
        raise SystemExit(f"{label}: invalid source region")
    content = content[:first] + opening + content[first:last] + closing + content[last:]
    path.write_text(content)


# Linux 3.18 still uses is_compat_task() for the 32-bit compat ABI.
nomount_h = TARGET / "nomount.h"
replace_once(
    nomount_h,
    '#define NOMOUNT_BASE_VERSION "22"',
    '#define NOMOUNT_BASE_VERSION "22"\n#define NM_LINUX_318_PORT 1\n\n#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 5, 0)\n#define in_compat_syscall() is_compat_task()\n#endif',
    "NoMount 3.18 port marker and compat syscall helper",
)

# iterate_shared was added in 4.7. Linux 3.18 exposes only ->iterate.
replace_once(
    nomount_h,
    """static inline int nm_call_iterate(struct file *file, struct dir_context *ctx, const struct file_operations *fop)
{
    if (fop->iterate_shared)
        return fop->iterate_shared(file, ctx);
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    else if (fop->iterate)
        return fop->iterate(file, ctx);
#endif
    return -ENOTDIR;
}""",
    """static inline int nm_call_iterate(struct file *file, struct dir_context *ctx, const struct file_operations *fop)
{
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)
    if (fop->iterate_shared)
        return fop->iterate_shared(file, ctx);
#endif
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    if (fop->iterate)
        return fop->iterate(file, ctx);
#endif
    return -ENOTDIR;
}""",
    "NoMount legacy directory iteration helper",
)
replace_once(
    nomount_h,
    """static inline struct nm_dir_ops *nm_get_nm_fop(const struct file_operations *fop) {
    if (unlikely(!fop)) return NULL;
    if (fop->iterate_shared == nm_hijacked_iterate_dir)
        return container_of(fop, struct nm_dir_ops, fake_fop);
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    if (fop->iterate == nm_hijacked_iterate_dir)
        return container_of(fop, struct nm_dir_ops, fake_fop);
#endif
    return NULL;
}""",
    """static inline struct nm_dir_ops *nm_get_nm_fop(const struct file_operations *fop) {
    if (unlikely(!fop)) return NULL;
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)
    if (fop->iterate_shared == nm_hijacked_iterate_dir)
        return container_of(fop, struct nm_dir_ops, fake_fop);
#endif
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    if (fop->iterate == nm_hijacked_iterate_dir)
        return container_of(fop, struct nm_dir_ops, fake_fop);
#endif
    return NULL;
}""",
    "NoMount legacy fop lookup",
)

nomount_c = TARGET / "nomount.c"

# The 3.18 VFS dispatches xattrs through inode_operations. The handler-array
# proxy API used by the newer NoMount source is retained only on 4.4+.
wrap_region(
    nomount_c,
    "struct nm_xattr_proxy {",
    "static int nm_d_revalidate_common",
    "#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)\n",
    "#endif /* Linux 4.4+ xattr_handler ABI */\n\n",
    "NoMount modern xattr handler callbacks",
)

legacy_xattr = """#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 4, 0)
static ssize_t nm_getxattr(struct dentry *dentry, const char *name,
                           void *buffer, size_t size)
{
    struct nm_inode_info *info = d_backing_inode(dentry)->i_private;

    if (unlikely(!info))
        return -EIO;
    if (!info->r_path.dentry)
        return -ENODATA;
    return vfs_getxattr(info->r_path.dentry, name, buffer, size);
}

static int nm_setxattr(struct dentry *dentry, const char *name,
                       const void *value, size_t size, int flags)
{
    struct nm_inode_info *info = d_backing_inode(dentry)->i_private;

    if (unlikely(!info))
        return -EIO;
    if (!info->r_path.dentry)
        return -EOPNOTSUPP;
    return vfs_setxattr(info->r_path.dentry, name, value, size, flags);
}

static int nm_removexattr(struct dentry *dentry, const char *name)
{
    struct nm_inode_info *info = d_backing_inode(dentry)->i_private;

    if (unlikely(!info))
        return -EIO;
    if (!info->r_path.dentry)
        return -EOPNOTSUPP;
    return vfs_removexattr(info->r_path.dentry, name);
}
#endif
"""
replace_once(
    nomount_c,
    "    return r_inode->i_op->listxattr(info->r_path.dentry, buffer, size);\n}\n",
    "    return vfs_listxattr(info->r_path.dentry, buffer, size);\n}\n\n" + legacy_xattr,
    "NoMount legacy xattr dispatch",
)

# Linux 3.18 symlink operations use follow_link/put_link; get_link arrived in 4.5.
old_get_link = """static const char *nm_get_link(struct dentry *dentry, struct inode *inode, struct delayed_call *done)
{
    struct nm_inode_info *info = inode->i_private;
    struct inode *real_inode;
    struct dentry *target_dentry;
    if (unlikely(!info || !info->r_path.dentry)) return ERR_PTR(-ECHILD);

    real_inode = d_backing_inode(info->r_path.dentry);
    target_dentry = dentry ? info->r_path.dentry : NULL;
    if (real_inode && real_inode->i_op && real_inode->i_op->get_link) {
        return real_inode->i_op->get_link(target_dentry, real_inode, done);
    }

    return ERR_PTR(-EINVAL);
}"""
new_link_ops = """#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 5, 0)
""" + old_get_link + """
#else
static void *nm_follow_link(struct dentry *dentry, struct nameidata *nd)
{
    struct nm_inode_info *info = d_backing_inode(dentry)->i_private;
    struct inode *real_inode;

    if (unlikely(!info || !info->r_path.dentry))
        return ERR_PTR(-ECHILD);

    real_inode = d_backing_inode(info->r_path.dentry);
    if (real_inode && real_inode->i_op && real_inode->i_op->follow_link)
        return real_inode->i_op->follow_link(info->r_path.dentry, nd);

    return ERR_PTR(-EINVAL);
}

static void nm_put_link(struct dentry *dentry, struct nameidata *nd, void *cookie)
{
    struct nm_inode_info *info = d_backing_inode(dentry)->i_private;
    struct inode *real_inode;

    if (!info || !info->r_path.dentry)
        return;

    real_inode = d_backing_inode(info->r_path.dentry);
    if (real_inode && real_inode->i_op && real_inode->i_op->put_link)
        real_inode->i_op->put_link(info->r_path.dentry, nd, cookie);
}
#endif"""
replace_once(nomount_c, old_get_link, new_link_ops, "NoMount legacy symlink callbacks")

replace_once(
    nomount_c,
    """    inode_lock(r_inode);
    err = notify_change(IDMAP_CALL info->r_path.dentry, attr, NULL);
    inode_unlock(r_inode);""",
    """#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 5, 0)
    mutex_lock(&r_inode->i_mutex);
#else
    inode_lock(r_inode);
#endif
    err = notify_change(IDMAP_CALL info->r_path.dentry, attr, NULL);
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 5, 0)
    mutex_unlock(&r_inode->i_mutex);
#else
    inode_unlock(r_inode);
#endif""",
    "NoMount legacy inode mutex",
)

replace_once(
    nomount_c,
    """    .read = generic_read_dir,
    .iterate_shared = nm_dir_iterate_dir,
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    .iterate = nm_dir_iterate_dir,
#endif""",
    """    .read = generic_read_dir,
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)
    .iterate_shared = nm_dir_iterate_dir,
#endif
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    .iterate = nm_dir_iterate_dir,
#endif""",
    "NoMount legacy iterate fops initializer",
)
replace_once(
    nomount_c,
    """    bool iterate = fop && (fop->iterate_shared
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
        || fop->iterate
#endif
    );""",
    """    bool iterate = false;
    if (fop) {
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)
        iterate = fop->iterate_shared != NULL;
#endif
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
        iterate = iterate || (fop->iterate != NULL);
#endif
    }""",
    "NoMount legacy iterate detection",
)
replace_once(
    nomount_c,
    """        if (fop->iterate_shared) ops->fake_fop.iterate_shared = nm_hijacked_iterate_dir;
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
        if (fop->iterate) ops->fake_fop.iterate = nm_hijacked_iterate_dir;
#endif""",
    """#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)
        if (fop->iterate_shared) ops->fake_fop.iterate_shared = nm_hijacked_iterate_dir;
#endif
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
        if (fop->iterate) ops->fake_fop.iterate = nm_hijacked_iterate_dir;
#endif""",
    "NoMount legacy iterate forwarding",
)

replace_once(
    nomount_c,
    """static const struct inode_operations nm_file_iops = {
    .getattr = nm_getattr,
    .setattr = nm_setattr,
    .listxattr = nm_listxattr,
    .get_link = nm_get_link,
};""",
    """static const struct inode_operations nm_file_iops = {
    .getattr = nm_getattr,
    .setattr = nm_setattr,
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 4, 0)
    .getxattr = nm_getxattr,
    .setxattr = nm_setxattr,
    .removexattr = nm_removexattr,
#endif
    .listxattr = nm_listxattr,
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 5, 0)
    .get_link = nm_get_link,
#else
    .follow_link = nm_follow_link,
    .readlink = generic_readlink,
    .put_link = nm_put_link,
#endif
};""",
    "NoMount legacy file inode operations",
)
replace_once(
    nomount_c,
    """static const struct inode_operations nm_dir_iops = {
    .lookup = nm_dir_lookup,
    .getattr = nm_getattr,
    .setattr = nm_setattr,
    .listxattr = nm_listxattr,
};""",
    """static const struct inode_operations nm_dir_iops = {
    .lookup = nm_dir_lookup,
    .getattr = nm_getattr,
    .setattr = nm_setattr,
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 4, 0)
    .getxattr = nm_getxattr,
    .setxattr = nm_setxattr,
    .removexattr = nm_removexattr,
#endif
    .listxattr = nm_listxattr,
};""",
    "NoMount legacy directory inode operations",
)

replace_once(
    nomount_c,
    "    if (sb->s_xattr) {",
    "#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)\n    if (sb->s_xattr) {",
    "NoMount modern superblock xattr guard start",
)
replace_once(
    nomount_c,
    "    }\n\n    list_add_tail_rcu(&nm_sop->list, &nm_sb_list);",
    "    }\n#endif /* Linux 4.4+ superblock xattrs */\n\n    list_add_tail_rcu(&nm_sop->list, &nm_sb_list);",
    "NoMount modern superblock xattr guard end",
)

if "#define NM_LINUX_318_PORT 1" not in nomount_h.read_text():
    raise SystemExit("NoMount Linux 3.18 port marker missing")
if ".follow_link = nm_follow_link" not in nomount_c.read_text():
    raise SystemExit("NoMount legacy follow_link operations missing")
if ".getxattr = nm_getxattr" not in nomount_c.read_text():
    raise SystemExit("NoMount legacy getxattr operations missing")
if "iterate_shared" in nomount_h.read_text().split("static inline int nm_call_iterate", 1)[1].split("static inline struct dentry *nm_hash_and_lookup", 1)[0] and "#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 7, 0)" not in nomount_h.read_text():
    raise SystemExit("NoMount iterate_shared compatibility guard missing")

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
print("Linux 3.18 VFS adapters staged; CONFIG_NOMOUNT remains n pending compile/runtime validation.")
