# Mimir 3.18.140 — recovered binary reference

This document records facts extracted from the previously supplied flashable ZIP. It is a recovery reference, not a claim that the source tree has been reconstructed or that a new kernel has been built.

## Original artifact

- File: `Kernel-MTONEDEEN-bakaSU+SUSFS-kernel 3.18.zip`
- SHA-256: `ff8fce5eed51335748f313a709dac89673e001abeb30f2a4b7d24d6509e8b282`
- Payload: `Image.gz-dtb` (gzip kernel with appended DTB)
- Kernel release string: `3.18.140-Mimir/4c2a2689`
- Build string: GCC 4.9.x, build timestamp reported as 2026-10-21 20:21:32 UTC
- The ZIP contains no C source tree or patch series. The embedded kernel configuration and binary strings are recoverable; the original source implementation is not.

## Embedded IKCONFIG recovered from Image.gz-dtb

The following options were present in the embedded configuration:

```config
CONFIG_KSU=y
CONFIG_KSU_MULTI_MANAGER_SUPPORT=y
CONFIG_KSU_MANUAL_HOOK=y
CONFIG_KSU_MANUAL_HOOK_AUTO_SETUID_HOOK=y
CONFIG_KSU_MANUAL_HOOK_AUTO_INITRC_HOOK=y
CONFIG_KSU_MANUAL_HOOK_AUTO_INPUT_HOOK=y
CONFIG_KSU_SUSFS=y
CONFIG_KSU_SUSFS_SUS_PATH=y
CONFIG_KSU_SUSFS_SUS_MOUNT=y
CONFIG_KSU_SUSFS_SUS_KSTAT=y
CONFIG_KSU_SUSFS_SPOOF_UNAME=y
CONFIG_KSU_SUSFS_ENABLE_LOG=y
CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y
CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y
CONFIG_KSU_SUSFS_OPEN_REDIRECT=y
CONFIG_KSU_SUSFS_SUS_MAP=y
```

Also observed:
- `CONFIG_KSU_TRACEPOINT_HOOK` was not set.
- `CONFIG_KSU_SUSFS_INLINE_HOOK` was not set.

## SUSFS implementation evidence in the binary

The decompressed kernel contained strings naming SUSFS routines, including:

- `susfs_add_sus_path`, `susfs_add_sus_path_loop`, `susfs_is_inode_sus_path`
- `susfs_mark_inode_sus_kstat`, `susfs_add_sus_kstat`, `susfs_update_sus_kstat`
- `susfs_add_sus_map`
- `susfs_add_open_redirect`
- `susfs_open_redirect_spoof_do_sys_openat`
- `susfs_open_redirect_spoof_vfs_readlink`
- `susfs_open_redirect_spoof_do_proc_readlink`
- `susfs_open_redirect_spoof_vfs_statfs`
- `susfs_open_redirect_spoof_show_map_vma_srcu`

This is strong evidence that the old binary included custom SUSFS implementation code for these feature areas. It does not reveal the complete source, exact patch provenance, or prove every runtime path worked on every workload.

## Current source-tree comparison (branch audited 2026-10-30)

- Repository: `isabe8499-oss/kernel_motorola_msm8953`
- Work branch: `integration/bakasu-35253-susfs22-nomount`
- Current `arch/arm64/configs/deen_defconfig` has no `CONFIG_KSU`, `CONFIG_KSU_SUSFS`, or `CONFIG_NOMOUNT` entries.
- Current `fs/Kconfig` and `fs/Makefile` do not source/build NoMount.
- The integration branch currently contains audit documentation, not the old SUSFS C implementation or a completed NoMount port.

## BakaSU manager reference

- APK: `BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk`
- SHA-256: `11a276b3ceb7e3102be14d5274fc472ed4ff9192777db924c57009363628c85a`
- The device report in the audit showed a driver string `v4.2.0-rc3-7c383cfe-dirty` (35235/5), which differs from the supplied manager build 35253/6.
- Do not solve this by changing a version string alone. Verify the manager/daemon/kernel protocol and required hooks against the exact APK before packaging.

## NoMount v2.2.0 source reference

- Upstream: `maxsteeel/nomount`
- Release tag commit: `bf1847f98fed`
- Kernel source: `kernel/src/nomount.c`
- Retrieved blob SHA: `5ad954ee3b5c2f21be9de14c760101b60afb39d5`
- The source uses `rcu_guard()` and newer VFS/xattr interfaces. It is not a drop-in for Linux 3.18.140.
- Porting must explicitly adapt RCU lock lifetime/unlock paths, directory iteration callbacks, inode/dentry operations, xattr handling, path references, and object lifetime. Do not mechanically replace `rcu_guard()`.

## Engineering status

1. Recovered: original ZIP identity, embedded kernel configuration, kernel release/build string, and SUSFS symbol evidence.
2. Not recovered: original C source, exact SUSFS patch series, and exact original BakaSU source revision.
3. Not yet integrated: BakaSU build 35253/6, SUSFS 2.2.0 source, and NoMount v2.2.0.
4. Not yet validated: clean ARM64 build, boot, root manager handshake, NoMount protocol, filesystem behavior, or flashable ZIP.

Keep the known-good boot/recovery image. Do not flash a newly built kernel until build artifacts and device-side smoke tests have been checked.

## Outras opções relevantes confirmadas no IKCONFIG

A extração integral do IKCONFIG do mesmo ZIP confirma também:

```text
CONFIG_THREAD_INFO_IN_TASK=y
CONFIG_KEYS=y
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
# CONFIG_JUMP_LABEL is not set
```

Consequências para a reconstrução: manter `THREAD_INFO_IN_TASK` e `KEYS` habilitados; preservar `KALLSYMS_ALL` para a ocultação de símbolos; não habilitar `JUMP_LABEL` apenas para fazer o SUSFS funcionar, pois o Linux 3.18 possui fallback atômico de `static_key_slow_inc/dec` quando jump labels estão desativados.
