# pidfd backport for Linux 3.18 / arm64

Adapted from the Linux v5.4 pidfd implementation, particularly `kernel/pid.c`
and `kernel/signal.c`. This first port supports thread-group leaders only.

## Files changed

- `include/linux/pid.h`: adds the per-PID wait queue and declares pidfd file operations.
- `include/linux/init_task.h`: initializes the wait queue for `init_struct_pid`.
- `kernel/pid.c`: initializes allocated-PID wait queues; implements anon-inode
  pidfds, `poll()` exit notification and `pidfd_open`.
- `kernel/signal.c`: wakes pollers at process exit and implements
  `pidfd_send_signal` using this tree's legacy `struct siginfo`.
- `include/uapi/asm-generic/unistd.h`: registers syscall numbers 424 and 434.
- `arch/arm64/include/asm/unistd32.h` and `arch/arm64/include/asm/unistd.h`:
  register compat syscall entries and extend the compat table size.
- `include/linux/syscalls.h`: declares syscall entry points.
- `tools/testing/selftests/pidfd_open_test.c`: runtime smoke test.

## Validation status

Source proposal only: not compiled or device-tested. Build against the exact
kernel configuration and toolchain before testing. Verify syscall table
generation, `pidfd_open(getpid(), 0)`, invalid arguments, `pidfd_send_signal`,
PID namespace checks, PID reuse, and `poll()` notification both before and
after the process is reaped. Do not flash until all checks pass.
