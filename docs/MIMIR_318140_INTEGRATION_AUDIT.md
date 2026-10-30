# Mimir 3.18.140 integration audit

## Target
- Device: Motorola One Deen (MSM8953), ARM64
- Kernel base: Linux 3.18.140
- Android target: 12
- Manager supplied by user: BakaSU v4.2.0-rc3, build 35253/6
- APK: BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk
- APK SHA-256: 11a276b3ceb7e3102be14d5274fc472ed4ff9192777db924c57009363628c85a
- Running kernel reported by device: 3.18.140-Mimir/4c2a2689
- Current driver reported by device: v4.2.0-rc3-7c383cfe-dirty (35235/5)
- SUSFS reported by device: 2.2.0

## Repository baseline audited on 2026-10-30
- Repository: isabe8499-oss/kernel_motorola_msm8953
- Default branch: lineage-18.1
- Default branch head at audit: 1f700e4c2e31c435358e7531dfc0c2e41e2a2684
- Makefile confirms VERSION=3, PATCHLEVEL=18, SUBLEVEL=140.
- Device defconfig: arch/arm64/configs/deen_defconfig.
- Integration branch: integration/bakasu-35253-susfs22-nomount
- The integration branch currently contains the audit document; no kernel source patches or defconfig modifications are claimed.
- Existing workflow: .github/workflows/mimir-build.yml. It delegates compilation to Vhmit/mimir-build-script v3.x-gcc; this is not yet a deterministic build of the proposed integration branch.

## BakaSU findings
- Official build guide: https://bakasu.org/guide/build
- Official manual-hook mode supports kernels from 3.4+, so the 3.18.140 target is within the stated manual-hook range.
- Tracepoint syscall redirect is for GKI 5.10+ and must not be selected for this target.
- The official BakaSU SUSFS documentation currently states that SUSFS support is for kernel 4.3+ and that non-GKI SUSFS needs manual backporting from the gki-android12-5.10 branch.
- Therefore, BakaSU manual-hook integration is a plausible target, but SUSFS 2.2.0 on Linux 3.18.140 is outside the current officially documented support range. The previously reported working SUSFS 2.2.0 implementation must be recovered as a specific historical/custom patch set and audited; do not assume current BakaSU SUSFS patches will apply.
- Current BakaSU setup script clones the moving main branch by default and modifies drivers/Makefile and drivers/Kconfig. It must not be run unreviewed; pin an exact commit after checking its kernel code against this 3.18 tree.
- Manager build number alone is not proof of driver protocol compatibility. Confirm the expected KSU version/protocol in the APK and the selected kernel revision before changing the driver version string.

## NoMount findings
- Upstream: https://github.com/maxsteeel/nomount
- Upstream documentation says kernels older than 5.10 need direct source integration or a device-specific LKM; the prebuilt LKM must not be assumed compatible.
- Current source files are kernel/src/{Kconfig,Makefile,nomount.c,nomount.h}.
- Current source uses rcu_guard() via a cleanup-attribute macro and newer VFS/xattr interfaces. This is not a drop-in implementation for 3.18.140.
- Porting requires a careful RCU conversion to primitives available in 3.18, ensuring every early return releases the read lock; also audit dir_context actor/iterate APIs, dentry/inode operation structures, xattr handlers, path/refcount ownership, and any newer helper macros.
- Do not perform a mechanical global replacement of rcu_guard(); lock lifetime and return paths must be reviewed function by function.
- Upstream setup.sh changes fs/Kconfig and fs/Makefile and creates a symlink. Do not pipe the remote script into the kernel tree; use a pinned source snapshot and reviewed changes.

## SUSFS recovery requirement
- The current integration branch tree did not contain SUSFS paths when audited.
- Recover the exact prior SUSFS 2.2.0 patch set from a known-good commit, archive, or the user's prior kernel tree.
- Validate all touched files and hooks against this exact 3.18.140 source. In particular, do not enable CONFIG_KSU_SUSFS or SUSFS feature symbols in deen_defconfig until the implementation and Kconfig definitions are present.
- Requested feature set to verify against recovered source: SUS_PATH, SUS_MOUNT, SUS_KSTAT, SUS_MAP, SPOOF_UNAME, SPOOF_CMDLINE_OR_BOOTCONFIG, HIDE_KSU_SUSFS_SYMBOLS, ENABLE_LOG, OPEN_REDIRECT, and SUS_MAP. Treat names as requirements to audit, not as proof that every symbol exists in the recovered 2.2.0 patch.

## Required implementation sequence
1. Preserve the existing lineage-18.1 branch and work only on integration/bakasu-35253-susfs22-nomount.
2. Recover the exact previously working SUSFS 2.2.0 source/patch set and identify its source commit/provenance.
3. Pin BakaSU kernel source to an exact revision; use manual hooks, not tracepoint hooks; verify manager/kernel protocol compatibility for build 35253/6.
4. Port NoMount source to 3.18.140 and review RCU, VFS, xattr, locking, lifetime, and compat paths.
5. Integrate Kconfig/Makefiles and update deen_defconfig only after source and symbols exist.
6. Replace/adapt the delegated workflow so it builds this repository and branch deterministically.
7. Run defconfig resolution checks, compile the ARM64 kernel, inspect Image/dtb/modules, package a recovery ZIP, and validate ZIP contents and SHA-256.
8. Keep a known-good boot image and recovery path. Do not flash an unvalidated image.

## Safety and status
No kernel source integration, successful compilation, boot test, or flashable ZIP is claimed by this audit. NoMount and SUSFS are kernel-VFS modifications with boot and filesystem stability risks. A build artifact is not considered validated until the target device boots and basic filesystem/root operations pass.
