# Mimir 3.18.140 integration audit

## Target
- Device: Motorola One Deen (MSM8953), ARM64
- Kernel base: Linux 3.18.140
- Android target: 12
- Manager supplied by user: BakaSU v4.2.0-rc3, build 35253/6 (APK filename: BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk)
- Running kernel reported by device: 3.18.140-Mimir/4c2a2689
- Current driver reported by device: v4.2.0-rc3-7c383cfe-dirty (35235/5)
- SUSFS reported by device: 2.2.0

## Repository baseline audited on 2026-10-30
- Repository: isabe8499-oss/kernel_motorola_msm8953
- Default branch: lineage-18.1
- Default branch head: 1f700e4c2e31c435358e7531dfc0c2e41e2a2684
- Makefile confirms VERSION=3, PATCHLEVEL=18, SUBLEVEL=140.
- Device defconfig exists at arch/arm64/configs/deen_defconfig.
- The audited branch tree contains no paths named SUSFS and no BakaSU/KernelSU integration paths.
- Existing workflow: .github/workflows/mimir-build.yml. It delegates compilation to Vhmit/mimir-build-script v3.x-gcc.

## NoMount integration findings
- Upstream: https://github.com/maxsteeel/nomount
- Upstream documentation says kernels older than 5.10 need direct source integration or a device-specific LKM; the prebuilt LKM should not be assumed compatible.
- Upstream manual integration uses fs/Kconfig, fs/Makefile, and fs/nomount/{Kconfig,Makefile,nomount.c,nomount.h}.
- The current upstream source uses `rcu_guard()` in its RCU read-side path. This is not part of the 3.18-era RCU API, so a compatibility adaptation is required; it must preserve all early-return unlock paths and RCU/refcount rules.
- The upstream Makefile also probes for newer xattr callback signatures. The old 3.18 xattr/VFS interfaces must be checked and adapted rather than assumed compatible.
- Upstream setup script is at kernel/setup.sh. It creates a symlink and edits fs/Kconfig and fs/Makefile; it must be reviewed and tested against this 3.18 tree before execution. Do not pipe an unreviewed remote script into a privileged shell.

## BakaSU integration findings
- Upstream: https://github.com/Baka-SU/BakaSU
- The setup script clones the moving main branch by default. That is not sufficiently reproducible for this build.
- Pin a verified commit/tag after confirming it implements the manager protocol expected by the supplied 35253/6 APK. Do not infer compatibility from APK version text alone.
- Audit its manual-hook and SELinux compatibility checks against this kernel's 3.18.140 source before enabling CONFIG_KSU.

## Required work before a flashable build
1. Recover or reintroduce the complete SUSFS 2.2.0 source/patch set and validate every required hook against this exact 3.18.140 tree.
2. Select and pin the BakaSU kernel-side revision that corresponds to manager protocol/build 35253/6.
3. Port NoMount's VFS integration to this kernel's path-walk, RCU, xattr and directory iteration APIs; resolve compile errors and verify locking/refcount semantics.
4. Update deen_defconfig only after Kconfig symbols and source files are present.
5. Replace or adapt the current delegated build workflow so it builds this repository/branch deterministically, then run config checks, full ARM64 build, package checks, and preserve the prior boot image for recovery.

## Safety
No kernel source integration or defconfig change is claimed by this audit. No flashable ZIP should be produced until the above checks pass. Keep the existing lineage-18.1 branch unchanged.
