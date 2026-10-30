#!/usr/bin/env python3
"""Apply the pinned BakaSU 35253 overlay for this Linux 3.18.140 tree."""
from pathlib import Path
import subprocess
import sys

EXPECTED = "5785bdb8091304322f597f67d50e0b79f9815cb2"
root = Path(__file__).resolve().parents[1]
ksu = root / "KernelSU"
kernel = ksu / "kernel"

def run(*args):
    return subprocess.check_output(args, cwd=ksu, text=True).strip()

actual = run("git", "rev-parse", "HEAD")
if actual != EXPECTED:
    raise SystemExit(f"BakaSU pin mismatch: expected {EXPECTED}, found {actual}")

def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text()
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{label}: expected one exact source block, found {count}")
    path.write_text(text.replace(old, new, 1))

# 1) SUSFS is a feature, not the inline-hook method. Keep Manual Hook selectable.
kconfig = kernel / "Kconfig"
text = kconfig.read_text()
old_block = '''config KSU_SUSFS
\tbool "SUSFS Inline Hook"
\tdepends on THREAD_INFO_IN_TASK && 64BIT
\thelp
\t  Patch and Enable SUSFS to kernel with KernelSU.
\t  SuSFS Officially support kernel 5.10+
\t  This KSU driver support it for 4.3+ in KSU side, 
\t  But the kernel side susfs compatibility MUST completed by yourself.
'''
new_block = '''config KSU_SUSFS
\tbool "Enable SUSFS support"
\tdepends on KSU && THREAD_INFO_IN_TASK && 64BIT
\thelp
\t  Enable the SUSFS feature layer independently of the KernelSU hook method.
\t  The selected hook method remains Manual Hook on legacy kernels; the
\t  SUSFS kernel-side compatibility patches must be present before enabling.
'''
if old_block in text:
    text = text.replace(old_block, "", 1)
    choice_end = text.index("endchoice")
    insert = choice_end + len("endchoice")
    text = text[:insert] + "\n\n" + new_block + text[insert:]
elif new_block not in text:
    raise SystemExit("Kconfig: unexpected KSU_SUSFS choice block")
kconfig.write_text(text)

# 2) Manual Hook remains the active hook path; run SUSFS checks/init as an
#    independent feature when both symbols are enabled.
kbuild = kernel / "Kbuild"
old_manual_marker = '''else ifdef CONFIG_KSU_MANUAL_HOOK
  $(info -- $(REPO_NAME): using Manual Hook)
  include $(KSU_SRC)/tools/manual_hook_check.mk
else ifdef CONFIG_KSU_SUSFS
'''
new_manual_marker = '''else ifdef CONFIG_KSU_MANUAL_HOOK
  $(info -- $(REPO_NAME): using Manual Hook)
  include $(KSU_SRC)/tools/manual_hook_check.mk
  ifdef CONFIG_KSU_SUSFS
    include $(KSU_SRC)/tools/susfs_compat.mk
    ifeq ($(shell test -e $(srctree)/fs/susfs.c; echo $$?),0)
      $(eval SUSFS_VERSION=$(shell cat $(srctree)/include/linux/susfs.h | grep -E '^#define SUSFS_VERSION' | cut -d' ' -f3 | sed 's/"//g'))
      $(info )
      $(info -- SUSFS_VERSION: $(SUSFS_VERSION))
    else
      $(info -- SUSFS source is not integrated in the target kernel.)
      $(error CONFIG_KSU_SUSFS requires fs/susfs.c and include/linux/susfs.h)
    endif
  endif
else ifdef CONFIG_KSU_SUSFS
'''
replace_once(kbuild, old_manual_marker, new_manual_marker, "Kbuild Manual Hook/SUSFS split")

# Linux 3.18 uses user-string syscall prototypes for stat/faccessat, not
# struct filename **. This define selects BakaSU's legacy-safe handler ABI.
text = kbuild.read_text()
marker = "kernelsu-objs := core/init.o\n"
if "KSU_COMPAT_LEGACY_USERPATH" not in text:
    if marker not in text:
        raise SystemExit("Kbuild: object list marker not found")
    text = text.replace(marker, marker + "\nifeq ($(VERSION),3)\nifeq ($(PATCHLEVEL),18)\nccflags-y += -DKSU_COMPAT_LEGACY_USERPATH\nendif\nendif\n", 1)
    kbuild.write_text(text)

# 3) Initialise SUSFS after Manual Hook's LSM hook setup; do not hide the
#    call behind the mutually-exclusive hook-method #elif chain.
init = kernel / "core/init.c"
old_init = '''#elif defined(CONFIG_KSU_MANUAL_HOOK)
// only lsm hook need call init
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 8, 0)
    ksu_lsm_hook_built_in_init();
#endif
#elif defined(CONFIG_KSU_SUSFS)
'''
new_init = '''#elif defined(CONFIG_KSU_MANUAL_HOOK)
// only lsm hook need call init
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 8, 0)
    ksu_lsm_hook_built_in_init();
#endif
#ifdef CONFIG_KSU_SUSFS
    susfs_init();
#endif
#elif defined(CONFIG_KSU_SUSFS)
'''
replace_once(init, old_init, new_init, "init Manual Hook + SUSFS")

# The SUSFS feature must not override the selected Manual Hook path in the
# runtime initrc/input dispatcher. The vfs_fstat helper belongs to Inline Hook.
runtime = kernel / "runtime/ksud_integration.c"
old_runtime = """#elif defined(CONFIG_KSU_SUSFS)
    DEFINE_STATIC_KEY_TRUE(ksu_is_init_rc_hook_enabled);"""
new_runtime = """#elif defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_KSU_MANUAL_HOOK)
    DEFINE_STATIC_KEY_TRUE(ksu_is_init_rc_hook_enabled);"""
replace_once(runtime, old_runtime, new_runtime, "runtime Manual Hook precedence")
old_fstat = """#ifdef CONFIG_KSU_SUSFS
void ksu_handle_vfs_fstat"""
new_fstat = """#if defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_KSU_MANUAL_HOOK)
void ksu_handle_vfs_fstat"""
replace_once(runtime, old_fstat, new_fstat, "runtime Inline Hook-only fstat")

# 4) Force the user-pointer handler ABI for old syscall APIs, even with SUSFS.
sucompat_h = kernel / "feature/sucompat.h"
old_proto = "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_faccessat"
new_proto = "#if defined(CONFIG_KSU_SUSFS) && !defined(KSU_COMPAT_LEGACY_USERPATH)\nint ksu_handle_faccessat"
replace_once(sucompat_h, old_proto, new_proto, "sucompat.h legacy prototypes")

sucompat_c = kernel / "feature/sucompat.c"
old_faccess = "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_faccessat"
new_faccess = "#if defined(CONFIG_KSU_SUSFS) && !defined(KSU_COMPAT_LEGACY_USERPATH)\nint ksu_handle_faccessat"
replace_once(sucompat_c, old_faccess, new_faccess, "sucompat.c faccessat ABI")
old_stat = "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_stat"
new_stat = "#if defined(CONFIG_KSU_SUSFS) && !defined(KSU_COMPAT_LEGACY_USERPATH)\nint ksu_handle_stat"
replace_once(sucompat_c, old_stat, new_stat, "sucompat.c stat ABI")

# 6) Static-key interface is not available in 3.18; the upstream compat
#    header correctly leaves KSU_COMPAT_USE_STATIC_KEY undefined before 4.3.
compat_h = kernel / "compat/kernel_compat.h"
compat_text = compat_h.read_text()
if "LINUX_VERSION_CODE >= KERNEL_VERSION(4, 3, 0)" not in compat_text:
    raise SystemExit("kernel_compat.h static-key compatibility gate changed")
if "KSU_COMPAT_USE_STATIC_KEY" not in compat_text:
    raise SystemExit("kernel_compat.h missing expected static-key gate")

# Verify overlay invariants.
assert "config KSU_SUSFS\n\tbool \"Enable SUSFS support\"" in kconfig.read_text()
assert "include $(KSU_SRC)/tools/manual_hook_check.mk" in kbuild.read_text()
assert "include $(KSU_SRC)/tools/susfs_compat.mk" in kbuild.read_text()
assert "    susfs_init();" in init.read_text()
assert "KSU_COMPAT_LEGACY_USERPATH" in sucompat_h.read_text()
assert sucompat_c.read_text().count("!defined(KSU_COMPAT_LEGACY_USERPATH)") == 2

print("Applied BakaSU Linux 3.18.140 overlay.")
print(f"BakaSU commit: {actual}")
print("Manual Hook remains the hook method; SUSFS is an independent feature.")
print("Legacy user-pointer ABI selected for fs/open.c and fs/stat.c.")
print("No Kconfig option is enabled by this script.")
