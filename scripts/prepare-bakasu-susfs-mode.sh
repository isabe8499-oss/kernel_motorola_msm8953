#!/usr/bin/env bash
set -euo pipefail

EXPECTED_BAKASU_SHA="5785bdb8091304322f597f67d50e0b79f9815cb2"
ACTUAL_BAKASU_SHA="$(git -C KernelSU rev-parse HEAD)"
if [[ "$ACTUAL_BAKASU_SHA" != "$EXPECTED_BAKASU_SHA" ]]; then
  echo "Unexpected BakaSU source: $ACTUAL_BAKASU_SHA" >&2
  exit 1
fi

python3 - <<'PY'
from pathlib import Path

ROOT = Path("KernelSU/kernel")

def read(rel):
    return (ROOT / rel).read_text()

def write(rel, content):
    (ROOT / rel).write_text(content)

def replace_once(rel, old, new, label):
    content = read(rel)
    old_count = content.count(old)
    new_count = content.count(new)
    if old_count == 1 and new_count == 0:
        write(rel, content.replace(old, new, 1))
    elif old_count == 0 and new_count == 1:
        return
    else:
        raise SystemExit(f"{label}: expected one pristine or one patched anchor; old={old_count}, new={new_count}")

# KSU_SUSFS used to be both a hook method and the feature gate. Split those
# meanings so legacy Manual Hook can coexist with SUSFS features.
kconfig_path = ROOT / "Kconfig"
kconfig = kconfig_path.read_text()
if "config KSU_SUSFS_INLINE_HOOK" not in kconfig:
    start = kconfig.find("config KSU_SUSFS\n")
    end = kconfig.find("\nendchoice", start)
    if start < 0 or end < 0:
        raise SystemExit("Kconfig: cannot locate KSU_SUSFS choice entry")
    replacement = """config KSU_SUSFS_INLINE_HOOK
\tbool "SUSFS Inline Hook"
\tdepends on THREAD_INFO_IN_TASK && 64BIT
\tselect KSU_SUSFS
\thelp
\t  Select the SUSFS inline-hook method. The SUSFS feature itself is
\t  configured separately so it can coexist with KSU_MANUAL_HOOK.
"""
    kconfig = kconfig[:start] + replacement + kconfig[end:]
    choice_end = kconfig.find("\nendchoice", start) + len("\nendchoice")
    feature = """

config KSU_SUSFS
\tbool "SUSFS feature support"
\tdepends on KSU && 64BIT
\tdefault n
\thelp
\t  Enable SUSFS features independently from the selected KernelSU hook
\t  method. On legacy kernels, combine this with KSU_MANUAL_HOOK.
"""
    kconfig = kconfig[:choice_end] + feature + kconfig[choice_end:]
    kconfig_path.write_text(kconfig)
elif 'bool "SUSFS feature support"' not in kconfig:
    raise SystemExit("Kconfig: partial SUSFS split detected")

replace_once(
    "Kbuild",
    "else ifdef CONFIG_KSU_SUSFS",
    "else ifdef CONFIG_KSU_SUSFS_INLINE_HOOK",
    "Kbuild hook-method selector",
)

init_old = """#elif defined(CONFIG_KSU_SUSFS)
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 8, 0)
    ksu_lsm_hook_built_in_init();
#endif
    susfs_init();
#else
#error "Unsupported hook type"
#endif"""
init_new = """#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 8, 0)
    ksu_lsm_hook_built_in_init();
#endif
#else
#error "Unsupported hook type"
#endif

#ifdef CONFIG_KSU_SUSFS
    susfs_init();
#endif"""
replace_once("core/init.c", init_old, init_new, "core/init.c hook init")

sucompat_header_old = """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);
#else
int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);
int ksu_handle_post_execve(int *fd, const char *filename, void *argv, void *envp, int *flags, int *retval);
#endif // #ifdef CONFIG_KSU_SUSFS"""
sucompat_header_new = """#ifdef CONFIG_KSU_SUSFS_INLINE_HOOK
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);
#else
int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);
int ksu_handle_post_execve(int *fd, const char *filename, void *argv, void *envp, int *flags, int *retval);
#endif // #ifdef CONFIG_KSU_SUSFS_INLINE_HOOK"""
replace_once("feature/sucompat.h", sucompat_header_old, sucompat_header_new, "sucompat.h handler ABI")

replace_once(
    "feature/sucompat.c",
    "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_execveat_sucompat",
    "#ifdef CONFIG_KSU_SUSFS_INLINE_HOOK\nint ksu_handle_execveat_sucompat",
    "sucompat execveat inline-only wrapper",
)
replace_once(
    "feature/sucompat.c",
    "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_faccessat",
    "#ifdef CONFIG_KSU_SUSFS_INLINE_HOOK\nint ksu_handle_faccessat",
    "sucompat faccessat handler ABI",
)
replace_once(
    "feature/sucompat.c",
    "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_stat",
    "#ifdef CONFIG_KSU_SUSFS_INLINE_HOOK\nint ksu_handle_stat",
    "sucompat stat handler ABI",
)

preinit_h = read("preinit/preinit.h")
old_count = preinit_h.count("#elif defined(CONFIG_KSU_SUSFS)")
new_count = preinit_h.count("#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)")
if old_count == 2 and new_count == 0:
    preinit_h = preinit_h.replace("#elif defined(CONFIG_KSU_SUSFS)", "#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)")
    write("preinit/preinit.h", preinit_h)
elif not (old_count == 0 and new_count == 2):
    raise SystemExit(f"preinit.h hook selector mismatch: old={old_count}, new={new_count}")

replace_once(
    "preinit/preinit.c",
    "#elif defined(CONFIG_KSU_SUSFS)",
    "#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)",
    "preinit.c hook selector",
)
replace_once(
    "runtime/ksud_integration.c",
    "#elif defined(CONFIG_KSU_SUSFS)\n    DEFINE_STATIC_KEY_TRUE(ksu_is_init_rc_hook_enabled);",
    "#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)\n    DEFINE_STATIC_KEY_TRUE(ksu_is_init_rc_hook_enabled);",
    "ksud integration hook selector",
)
replace_once(
    "runtime/ksud_integration.c",
    "#ifdef CONFIG_KSU_SUSFS\nvoid ksu_handle_vfs_fstat",
    "#ifdef CONFIG_KSU_SUSFS_INLINE_HOOK\nvoid ksu_handle_vfs_fstat",
    "ksud inline-only fstat hook",
)
replace_once(
    "supercall/dispatch.c",
    '#elif defined(CONFIG_KSU_SUSFS)\n    const char *type = "Inline";',
    '#elif defined(CONFIG_KSU_SUSFS_INLINE_HOOK)\n    const char *type = "Inline";',
    "manager hook-type reporting",
)

# Keep the feature-gated SUSFS process marker branch in sucompat.h and the
# SUSFS command/umount branches in dispatch.c. They are features, not hook modes.
print("BakaSU prepared: Manual Hook and SUSFS feature are now independent.")
PY
