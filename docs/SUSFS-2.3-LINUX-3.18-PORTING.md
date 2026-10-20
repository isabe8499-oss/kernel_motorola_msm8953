# SUSFS 2.3 port status for Deen (Linux 3.18.140)

Target branch: `deen-bakasu-susfs23-port-test`

Pinned inputs:
- BakaSU: `7c383cfeef3a2ac450f2f1273dae74bd50356d31`
- SUSFS: `wxx9248/susfs4ksu@71345ded5af28f55d76ebcdc7a9df9cea56111e1`
- Non-GKI hook script: `JackA1ltman/NonGKI_Kernel_Build_2nd@dcd789634247c77d8549a42aef232c680a905585`

## Verified status

- BakaSU manual-hook baseline compiles successfully in GitHub Actions. Artifact: `deen-linux-3.18.140-bakasu-baseline-no-susfs`.
- That baseline explicitly has `CONFIG_KSU_SUSFS` disabled. It is not the requested SUSFS kernel and has not been boot-tested on hardware.
- The SUSFS 4.9 patch is not cleanly applicable to this Linux 3.18 tree. The strict probe correctly fails; do not treat the inline-hook script's exit status as proof that SUSFS core integration is complete.
- The pinned SUSFS tree does not contain `kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch`; the KernelSU glue step must be authored for this pinned BakaSU tree rather than copied from a missing file.

## Port strategy

Do not apply the complete `50_add_susfs_in_kernel-4.9.patch` with forced offsets. Port in small, reviewable layers and make each layer compile before proceeding.

### Layer 0 — reproducibility and baseline

- Keep the BakaSU baseline workflow unchanged and available as a known-good reference.
- Keep all SUSFS work on this feature branch.
- Every integration attempt must report rejected hunks, compiler output, resulting config, and the exact pinned commits.
- Do not publish a flashable ZIP until a SUSFS-enabled build succeeds, the expected SUSFS symbols are present, and the image format is validated. A successful compile alone does not establish boot compatibility.

### Layer 1 — build plumbing and public interfaces

Files to adapt:
- `fs/Makefile`: add `susfs.o` only after the source has compatible declarations and dependencies.
- `include/linux/susfs.h`, `include/linux/susfs_def.h`: audit includes and macros against this tree's headers before enabling the feature.
- `fs/Kconfig` and BakaSU's `drivers/kernelsu/Kconfig`: define a coherent SUSFS option set and glue for the pinned BakaSU revision. Do not enable options whose hooks have not been ported.
- KernelSU glue: add only the SUSFS command dispatch and state access actually required by this BakaSU revision; do not assume a patch from a different KernelSU fork applies.

Exit criteria: configuration is reproducible, all feature dependencies are explicit, and a minimal SUSFS translation unit can compile without unresolved declarations.

### Layer 2 — VFS path lookup (highest-risk API mismatch)

The 4.9 patch expects lookup helpers and control flow that do not match this 3.18 tree. The target currently has:
- `lookup_dcache(struct qstr *name, struct dentry *dir, unsigned int flags, bool *need_lookup)`
- `__lookup_hash(struct qstr *name, struct dentry *base, unsigned int flags)`
- `lookup_fast(struct nameidata *nd, struct path *path, struct inode **inode)`
- `lookup_last(struct nameidata *nd, struct path *path)`
- `filename_lookup(int dfd, struct filename *name, unsigned int flags, struct nameidata *nd)`

The 4.9 patch has hunks for `lookup_slow`, `do_filp_open`, `lookup_open`, and `do_last` whose control flow is not a direct match for this tree. Re-derive each hook from the actual 3.18 call graph; do not rename or synthesize helpers just to satisfy patch context.

Exit criteria: each path-lookup hook is placed at a documented point with correct lock/refcount semantics; build and run targeted path-lookup tests before adding other features.

### Layer 3 — mount namespace representation

Files: `fs/namespace.c`, `fs/proc_namespace.c`, `fs/notify/fdinfo.c`, `fs/pnode.h`, `include/linux/mount.h`.

The 4.9 patch changes mount allocation/grouping, mount cloning, mount lookup, namespace copying, and proc mount rendering. These are coupled operations. Port them as one reviewed layer; do not add a SUSFS mount flag or fake mount IDs without auditing allocation, clone, teardown, namespace propagation, and all readers.

Exit criteria: no rejected hunks; mount/unmount, bind mounts, namespace cloning, proc mount output, and inotify fdinfo regressions checked.

### Layer 4 — stat and proc surfaces

Files: `fs/stat.c`, `fs/statfs.c`, `fs/proc/cmdline.c`, `fs/proc/fd.c`, `fs/proc/task_mmu.c`, `fs/readdir.c`, `fs/exec.c`, `fs/read_write.c`, `fs/open.c`, `kernel/sys.c`, `kernel/kallsyms.c`, `mm/memory.c`, SELinux hooks.

Each feature must be gated by its own Kconfig symbol and tested separately. Avoid introducing references to helpers/fields that only exist in newer VFS or mm implementations. Confirm that disabled options leave the original behavior unchanged.

## Current blocking findings

1. The generic 4.9 patch has multiple rejects in this 3.18 tree, especially `fs/namei.c`, `fs/namespace.c`, `fs/notify/fdinfo.c`, `fs/proc/cmdline.c`, `fs/proc/fd.c`, `fs/readdir.c`, `fs/stat.c`, and `mm/memory.c`.
2. The 3.18 path lookup API differs materially from the patch's expected helpers and call graph.
3. SUSFS core code depends on mount internals and kernel helpers that must be reconciled with the target's older structures and APIs.
4. The current baseline is BakaSU-only; no claim of SUSFS functionality or device boot compatibility is made.

## Acceptance gates before a flash package

- Zero rejected hunks and no forced patch application.
- `CONFIG_KSU=y`, manual hooks enabled, and the intended SUSFS feature options enabled in the final config.
- SUSFS core and all enabled hooks compile and link.
- Automated symbol/config audit passes; artifact contains kernel image and recorded config/commits/checksums.
- Image is structurally checked against the supplied Deen boot image layout.
- Device-side backup and recovery plan exists before any test flash. The baseline artifact must not be substituted for the final image.

## Confirmed hard blocker (2026-10-20)

The pinned BakaSU revision itself contains `kernel/tools/susfs_compat.mk` with an unconditional `$(error Please wait susfs update.)`. This is not merely a missing patch file: selecting BakaSU's `CONFIG_KSU_SUSFS` causes the SUSFS compatibility make fragment to stop the build until its SUSFS integration is updated. The same guard is present in BakaSU's current `main` at the time of this audit.

Upstream BakaSU build documentation also says SUSFS is no longer supported as a ready-made Non-GKI integration and requires manually backporting the patches from a matching `gki-android12-5.10` branch. The SUSFS 2.3 port pinned above explicitly targets Linux 4.9; its documented compatibility starts at kernel 4.9, not 3.18. ReSukiSU documentation has the same limitation: SUSFS backports are for kernel 4.3+, although its manual root hooks can work on older kernels.

Sources checked:
- BakaSU integration guide: https://bakasu.org/guide/build
- Pinned BakaSU compatibility guard: https://github.com/Baka-SU/BakaSU/blob/7c383cfeef3a2ac450f2f1273dae74bd50356d31/kernel/tools/susfs_compat.mk
- SUSFS 2.3 Linux 4.9 port: https://github.com/wxx9248/susfs4ksu
- ReSukiSU integration guide: https://resukisu.org/guide/build.html

### Decision

Do not enable `CONFIG_KSU_SUSFS` in the current BakaSU baseline and do not package the partial 3.18 patch experiment as a usable kernel. There is no verified maintained SUSFS 2.3 patch for Linux 3.18 in the pinned sources.

The valid next paths are:
1. Keep the known-buildable BakaSU manual-hook kernel and leave SUSFS disabled; or
2. Treat SUSFS as a separate, substantial kernel-port project: select a SUSFS/KSU source pair that does not hard-stop its build, port the kernel-side code from a compatible newer branch to Linux 3.18 VFS/SELinux APIs, then require a clean compile, symbol/config audit, boot-image layout validation, and device testing before packaging.

Switching to ReSukiSU alone does not solve the SUSFS problem: its published compatibility guidance still places the SUSFS backport floor above Linux 3.18. No flashable SUSFS ZIP should be produced until path 2 passes every gate above.

