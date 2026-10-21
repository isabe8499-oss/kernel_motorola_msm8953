# pidfd backport for Linux 3.18 / arm64

This backport is adapted from the Linux v5.4 pidfd implementation, in
particular `kernel/pid.c` and `kernel/signal.c`. It intentionally supports
thread-group leaders only, matching the initial pidfd ABI.

## Files changed

- `include/linux/pid.h`: adds a wait queue to `struct pid` and declares the
  pidfd file operations.
- `include/linux/init_task.h`: statically initializes the wait queue for
  `init_struct_pid`.
- `kernel/pid.c`: initializes each pid wait queue; implements pidfd file
  operations, poll notification, pidfd creation, and `pidfd_open`.
- `kernel/signal.c`: wakes pollers on process exit and implements
  `pidfd_send_signal`, adapting the upstream code to this tree's
  `struct siginfo` API.
- `include/uapi/asm-generic/unistd.h`: registers arm64 syscall numbers 424
  and 434 and extends the native syscall table size.
- `arch/arm64/include/asm/unistd32.h` and
  `arch/arm64/include/asm/unistd.h`: register the compat syscall entries and
  extend the compat table size.
- `include/linux/syscalls.h`: declares the syscall entry points.
- `tools/testing/selftests/pidfd_open_test.c`: minimal runtime smoke test.

## Validation status

This is a source backport proposal, not a validated device kernel. It must be
compiled against the exact kernel configuration and toolchain, then tested on
device. The smoke test only verifies that `pidfd_open(getpid(), 0)` returns a
valid descriptor. Additional tests are required for `pidfd_send_signal`,
`poll()` exit notification, PID namespace behavior, invalid descriptors,
and PID reuse. Do not flash a kernel until those tests pass.
