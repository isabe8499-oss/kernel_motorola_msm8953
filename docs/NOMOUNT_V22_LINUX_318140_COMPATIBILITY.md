# NoMount v2.2.0 — Linux 3.18.140 compatibility assessment

## Exact upstream baseline

- Repository: https://github.com/maxsteeel/nomount
- Release: v2.2.0 (605)
- Immutable tag commit: `bf1847f98fed382369c43bfd652cd93774b9b8e3`
- Kernel source blob: `kernel/src/nomount.c`
- Kernel source blob SHA: `5ad954ee3b5c2f21be9de14c760101b60afb39d5`
- Header blob SHA: `c850611ff1b37582c7f3e09058616096f8ef7930`
- Release archive SHA-256 (upstream release index): `d40277cb8f495b78711fb72e5f19a79ab2627eba2f0eb2aec60b5fc8019fae83`
- Protocol: v22. Driver and metamodule must be updated together. v22 CLI is not wire-compatible with a v21 driver.

## Confirmed Linux 3.18.140 API facts from this repository

Inspected the exact integration branch headers:

- `include/linux/rcupdate.h` provides `rcu_read_lock()` / `rcu_read_unlock()`; NoMount v2.2.0 uses `rcu_guard()` at four sites (source lines 25, 183, 1886, 1919). A manual RCU conversion is possible in principle but each scope and all early returns must be audited.
- `include/linux/fs.h` has `struct file_operations::iterate`, but no `iterate_shared`.
- The 3.18 `struct dir_context` is legacy: it contains `filldir_t actor`, `pos`, and this fork's `romnt` field. Contrary to the preliminary draft, `dir_emit()`, `dir_emit_dots()`, and `iterate_dir()` are present in this tree. Directory enumeration does not need a complete rewrite: guard direct `iterate_shared` references, adapt the callback's first argument (`void *` in legacy `filldir_t`) and preserve actor/position semantics. When creating the NoMount proxy context, copy `ctx->romnt` so the fork's read-only filtering remains correct.
- `include/linux/xattr.h` exposes the legacy `xattr_handler` callbacks: `.list(dentry,...)`, `.get(dentry,name,buffer,size,handler_flags)`, and `.set(dentry,name,value,size,flags,handler_flags)`. There is no `.__get`, `xattr_full_name()`, `__vfs_getxattr()` or modern `__vfs_setxattr()` interface. The proxy must forward the original handler using these exact legacy arguments, retaining prefix/suffix and handler flags and avoiding recursion through the replaced handler table.
- `include/linux/dcache.h` does provide `d_backing_inode()`.
- `include/linux/fs.h` provides `i_opflags` and `S_NOSEC`; these specific fields/flags are not blockers on this tree.
- The key subsystem headers expose `struct key_type` and `register_key_type()`; keyring-based control is therefore not ruled out by the header API alone.

## Porting work required before adding NoMount to Kconfig

1. **Directory enumeration:** use `.iterate` only on 3.18 and add a typed adapter from legacy `filldir_t(void *...)` to the NoMount proxy actor. Preserve `ctx->pos`, actor return values, and the fork-specific `romnt` field. `dir_emit()` already exists; audit normal and compat readdir paths.
2. **VFS operation hooks:** guard every `iterate_shared` member access and use `.iterate` on 3.18. NoMount's symlink operation also needs a separate legacy implementation: the target has `.follow_link`/`.put_link` and `nameidata`, not `.get_link`/`delayed_call`. Ensure the original filesystem's cookie release function is called exactly once.
3. **Xattr proxy:** replace the modern handler wrappers with the exact legacy `.get`/`.set`/`.list` signatures. Forward to the original handler on the backing dentry, preserving handler flags, names/prefixes, ACL/security semantics, buffer sizing and error codes.
4. **RCU and object lifetime:** audit all four `rcu_guard()` scopes (the upstream header uses GCC cleanup attributes) for nested read-side sections, early returns, references acquired while protected and deferred frees. The target provides `rcu_read_lock()`/`rcu_read_unlock()`; keep path/dentry/inode/dir-node references balanced. Do not mechanically replace the guard.
5. **Other API differences:** replace `inode_lock()`/`inode_unlock()` with the 3.18 inode mutex (`i_mutex`) under equivalent locking rules; handle the absent `DCACHE_OP_REAL` without assigning an arbitrary colliding flag; adapt `get_user_pages_fast()` to its legacy third `write` argument (the local `FOLL_WRITE` value is 1). Review `dentry_open()`, read/write, mmap and credentials against this tree.
6. **Protocol v22:** preserve the 24-byte `nm_rule_hdr` and 18-byte `nm_del_hdr` layouts, including alignment/packing and compat userspace handling. Test kernel driver and userspace CLI from the same v2.2.0 release.
7. **Concurrency/unload:** audit operation-table replacement/publication, RCU reclamation, inode eviction, module unload, open virtual files, and concurrent rule updates. The initial safe target should be built-in (`CONFIG_NOMOUNT=y`) unless the 3.18 module lifetime and unload path is fully proven.
8. **Build integration:** only after the source compiles against 3.18, add `fs/nomount/Kconfig`, `fs/nomount/Makefile`, the `source` line in `fs/Kconfig`, the object line in `fs/Makefile`, and then enable `CONFIG_NOMOUNT` in `deen_defconfig`.

## Current repository status

- The `NoMount` submodule is present and pinned to the exact v2.2.0 commit above.
- `scripts/stage-nomount-318.py` copies `nomount.c`, `nomount.h`, Kconfig and Makefile into `fs/nomount` during CI, changes upstream `default y` to `default n`, and wires the conditional Kconfig/Makefile entries. This is source staging only; it is not a Linux 3.18 compatibility port.
- The workflow pins the build helper (`Vhmit/mimir-build-script` commit `71abd60bb5c110a6de841a799b99af6fe2fa5f46`), GCC toolchain (`0d8d0f715973db533afb85725492c17c43e8dcc1`) and AnyKernel3 (`a3249880710e9702798bcb8f5211cc9f2e63e4a7`). It invokes the build helper with `-ksu`.
- A hard integration gate runs before compilation and deliberately blocks packaging until the Linux 3.18 NoMount marker/hooks and the full BakaSU/SUSFS feature set are present.
- No NoMount source port, successful ARM64 compile, boot test, or flashable ZIP is claimed by this assessment.

## Acceptance gates

- [ ] All compatibility changes are explicit and reviewed against the exact 3.18.140 headers.
- [ ] Kernel config resolves `CONFIG_NOMOUNT=y` and all expected KSU/SUSFS symbols without undefined Kconfig symbols.
- [ ] ARM64 compile succeeds with warnings reviewed (not merely ignored).
- [ ] Protocol v22 userspace communicates with the built-in driver.
- [ ] Test whiteout, file redirect, directory redirect, opaque directory, UID include/exclude, rule add/delete/list, and clear operations.
- [ ] Stress test concurrent lookup/readdir/open/mmap and rule updates; inspect dmesg for warnings, RCU stalls, refcount issues, and crashes.
- [ ] Package ZIP and verify contents/hash; retain known-good boot/recovery image before device testing.

This document is a compatibility assessment and implementation checklist, not a claim of a completed port.
