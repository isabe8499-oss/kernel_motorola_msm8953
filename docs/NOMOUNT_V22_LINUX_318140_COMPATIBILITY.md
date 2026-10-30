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
- The 3.18 `struct dir_context` is legacy: it contains `const filldir_t actor`, `pos`, and `romnt`. It does not expose the newer actor callback shape used by NoMount v2.2.0 (`ctx->actor` called with `name, namelen, offset, ino, d_type`) nor the newer `dir_emit()` interface. Directory enumeration requires a compatibility design, not just renaming `iterate_shared` to `iterate`.
- `include/linux/xattr.h` defines `struct xattr_handler` with `.list`, `.get`, and `.set`; there is no `.__get`. NoMount's proxy wrapper for `.__get` must be redesigned around the legacy `.get` callback and its exact signature/flags.
- `include/linux/dcache.h` does provide `d_backing_inode()`.
- `include/linux/fs.h` provides `i_opflags` and `S_NOSEC`; these specific fields/flags are not blockers on this tree.
- The key subsystem headers expose `struct key_type` and `register_key_type()`; keyring-based control is therefore not ruled out by the header API alone.

## Porting work required before adding NoMount to Kconfig

1. **Directory enumeration:** redesign the proxy callback to bridge legacy `filldir_t` semantics and the NoMount virtual-entry iterator. Audit position handling, stop/continue return values, 32/64-bit compat readdir paths, and every caller. Preserve original filesystem iteration behavior.
2. **VFS operation hooks:** map NoMount's `iterate_shared` paths to the 3.18 `.iterate` slot; inspect all `file_operations`, `inode_operations`, `dentry_operations`, and `super_operations` members against this tree before assigning them.
3. **Xattr proxy:** replace `.__get` interception with a correct legacy `.get` wrapper. Preserve original handler flags, name/prefix semantics, buffer sizing, error codes, and security behavior.
4. **RCU and object lifetime:** replace all four `rcu_guard()` scopes with explicit lock/unlock control flow. Audit nested read-side sections, every early return, references acquired while protected, and deferred frees. Keep path/dentry/inode/dir-node references balanced.
5. **File forwarding:** check `dentry_open()`, `read_iter`, `write_iter`, mmap, and credential behavior against the 3.18 declarations and implementation. Do not assume modern API signatures.
6. **Protocol v22:** preserve the 24-byte `nm_rule_hdr` and 18-byte `nm_del_hdr` layouts, including alignment/packing and compat userspace handling. Test kernel driver and userspace CLI from the same v2.2.0 release.
7. **Concurrency/unload:** audit operation-table replacement/publication, RCU reclamation, inode eviction, module unload, open virtual files, and concurrent rule updates. The initial safe target should be built-in (`CONFIG_NOMOUNT=y`) unless the 3.18 module lifetime and unload path is fully proven.
8. **Build integration:** only after the source compiles against 3.18, add `fs/nomount/Kconfig`, `fs/nomount/Makefile`, the `source` line in `fs/Kconfig`, the object line in `fs/Makefile`, and then enable `CONFIG_NOMOUNT` in `deen_defconfig`.

## Current repository status

- The integration branch has not yet received NoMount C/H sources or kernel build integration.
- The existing workflow delegates to a moving external build script (`Vhmit/mimir-build-script`, branch `v3.x-gcc`) rather than building a pinned, locally reviewed configuration from this branch. Its optional KSU input defaults to `n`; therefore a successful run of that workflow would not prove this BakaSU/SUSFS/NoMount target.
- No source port, compile, boot test, or flashable ZIP is claimed by this assessment.

## Acceptance gates

- [ ] All compatibility changes are explicit and reviewed against the exact 3.18.140 headers.
- [ ] Kernel config resolves `CONFIG_NOMOUNT=y` and all expected KSU/SUSFS symbols without undefined Kconfig symbols.
- [ ] ARM64 compile succeeds with warnings reviewed (not merely ignored).
- [ ] Protocol v22 userspace communicates with the built-in driver.
- [ ] Test whiteout, file redirect, directory redirect, opaque directory, UID include/exclude, rule add/delete/list, and clear operations.
- [ ] Stress test concurrent lookup/readdir/open/mmap and rule updates; inspect dmesg for warnings, RCU stalls, refcount issues, and crashes.
- [ ] Package ZIP and verify contents/hash; retain known-good boot/recovery image before device testing.

This document is a compatibility assessment and implementation checklist, not a claim of a completed port.
