# pidfd backport for the 3.18 arm64 kernel

This branch is a first-pass backport for the Motorola MSM8953 Linux 3.18 tree.
It deliberately uses the upstream syscall numbers:

- `pidfd_send_signal`: 424
- `pidfd_open`: 434

## Source references

- `kernel/pid.c`: `pidfd_open()` / pid reference ownership follows Linux v5.4.
- `kernel/pid.c`: pidfd file operations and poll behavior are adapted from Linux v5.10's `kernel/fork.c`.
- `kernel/signal.c`: `pidfd_send_signal()` follows the Linux v5.4 flow, adapted from `kernel_siginfo` to this tree's `struct siginfo`; AArch32 compat callers use `copy_siginfo_from_user32()`.
- `include/linux/pid.h`, `include/linux/init_task.h`, and signal exit notification: per-`struct pid` wait queue and exit wakeup are required for pollable descriptors.
- syscall tables and prototypes register the two entry points for AArch64 and AArch32 compat.

## Runtime smoke test

Build `tools/pidfd_open_test.c` and run it on the device after booting a kernel built from this branch. The test checks that `pidfd_open(getpid(), 0)` returns a valid fd with `FD_CLOEXEC`, that `pidfd_send_signal(fd, 0, NULL, 0)` succeeds, and that using the closed fd returns `EBADF`. Exit status 2 with `ENOSYS` means `pidfd_open` is not wired to the implementation.

## Validation status / review checklist

This is not a release-ready kernel build. The source edits have not yet been compiled against the device defconfig or tested on hardware. Before merging, run at least:

1. arm64 kernel build with the exact Motorola One deen defconfig and toolchain.
2. `pidfd_open(getpid(), 0)` returns a valid CLOEXEC fd.
3. `pidfd_open(0, 0)`, `pidfd_open(-1, 0)`, and nonzero flags return `EINVAL`.
4. `poll()` does not report readiness while the target process is alive and becomes readable after its thread group exits.
5. `pidfd_send_signal(fd, 0, NULL, 0)` and a controlled signal test succeed; a non-pidfd file descriptor returns `EBADF`.
6. AArch32 compat syscall-table build, if compat is enabled.

The 3.18 signal ABI and task-exit ordering differ from the upstream references; those are the highest-risk areas for compile/runtime review. Do not flash this branch until the build and runtime checks pass.
