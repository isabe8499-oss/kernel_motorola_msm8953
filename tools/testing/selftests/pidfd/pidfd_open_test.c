/*
 * Minimal pidfd_open smoke test for the Linux 3.18 pidfd backport.
 *
 * Build on the target ARM64 userspace:
 *   cc -Wall -Wextra -O2 -o pidfd_open_test pidfd_open_test.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif

int main(void)
{
    long fd;

    errno = 0;
    fd = syscall(SYS_pidfd_open, getpid(), 0U);
    if (fd < 0) {
        int err = errno;
        fprintf(stderr, "pidfd_open(getpid(), 0) failed: errno=%d (%s)\n",
                err, strerror(err));
        return err == ENOSYS ? 2 : 1;
    }

    printf("pidfd_open OK: fd=%ld\n", fd);
    if (close((int)fd) < 0) {
        perror("close(pidfd)");
        return 1;
    }

    errno = 0;
    fd = syscall(SYS_pidfd_open, getpid(), 1U);
    if (fd >= 0) {
        close((int)fd);
        fprintf(stderr, "pidfd_open unexpectedly accepted nonzero flags\n");
        return 1;
    }
    if (errno != EINVAL) {
        fprintf(stderr, "pidfd_open(flags=1): expected EINVAL, got %d (%s)\n",
                errno, strerror(errno));
        return 1;
    }

    puts("invalid-flags check OK");
    return 0;
}
