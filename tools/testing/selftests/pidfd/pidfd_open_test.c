#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif
#ifndef SYS_pidfd_send_signal
#define SYS_pidfd_send_signal 424
#endif

static int pidfd_open_sys(pid_t pid, unsigned int flags)
{
    return (int)syscall(SYS_pidfd_open, pid, flags);
}

static int pidfd_send_signal_sys(int pidfd, int sig)
{
    return (int)syscall(SYS_pidfd_send_signal, pidfd, sig, NULL, 0);
}

static int expect_einval(pid_t pid, unsigned int flags, const char *label)
{
    errno = 0;
    int fd = pidfd_open_sys(pid, flags);
    if (fd >= 0) {
        close(fd);
        fprintf(stderr, "%s: unexpectedly succeeded\n", label);
        return -1;
    }
    if (errno != EINVAL) {
        fprintf(stderr, "%s: expected EINVAL, got errno=%d\n", label, errno);
        return -1;
    }
    return 0;
}

int main(void)
{
    int self_fd = pidfd_open_sys(getpid(), 0);
    if (self_fd < 0) {
        perror("pidfd_open(getpid())");
        return errno == ENOSYS ? 2 : 1;
    }

    int fd_flags = fcntl(self_fd, F_GETFD);
    if (fd_flags < 0 || !(fd_flags & FD_CLOEXEC)) {
        fprintf(stderr, "pidfd_open did not set FD_CLOEXEC (F_GETFD=%d, errno=%d)\n",
                fd_flags, errno);
        close(self_fd);
        return 3;
    }

    struct pollfd pfd = { .fd = self_fd, .events = POLLIN };
    int ready = poll(&pfd, 1, 0);
    if (ready != 0) {
        fprintf(stderr, "live self pidfd unexpectedly ready: %d (revents=0x%x)\n",
                ready, pfd.revents);
        close(self_fd);
        return 4;
    }

    if (pidfd_send_signal_sys(self_fd, 0) < 0) {
        perror("pidfd_send_signal(self, 0)");
        close(self_fd);
        return 5;
    }

    if (expect_einval(0, 0, "pidfd_open(0)") < 0 ||
        expect_einval(-1, 0, "pidfd_open(-1)") < 0 ||
        expect_einval(getpid(), 1, "pidfd_open(nonzero flags)") < 0) {
        close(self_fd);
        return 6;
    }

    close(self_fd);
    errno = 0;
    if (pidfd_send_signal_sys(self_fd, 0) != -1 || errno != EBADF) {
        fprintf(stderr, "closed pidfd should fail with EBADF (errno=%d)\n", errno);
        return 7;
    }

    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 8;
    }
    if (child == 0) {
        for (;;)
            pause();
    }

    int child_fd = pidfd_open_sys(child, 0);
    if (child_fd < 0) {
        perror("pidfd_open(child)");
        kill(child, SIGKILL);
        waitpid(child, NULL, 0);
        return 9;
    }

    if (pidfd_send_signal_sys(child_fd, SIGTERM) < 0) {
        perror("pidfd_send_signal(child, SIGTERM)");
        kill(child, SIGKILL);
        waitpid(child, NULL, 0);
        close(child_fd);
        return 10;
    }

    int status;
    if (waitpid(child, &status, 0) != child) {
        perror("waitpid(child)");
        close(child_fd);
        return 11;
    }

    pfd.fd = child_fd;
    pfd.events = POLLIN;
    pfd.revents = 0;
    ready = poll(&pfd, 1, 3000);
    if (ready != 1 || !(pfd.revents & (POLLIN | POLLHUP))) {
        fprintf(stderr, "exited child pidfd did not become readable: poll=%d revents=0x%x errno=%d\n",
                ready, pfd.revents, errno);
        close(child_fd);
        return 12;
    }

    close(child_fd);
    puts("pidfd tests passed: open/CLOEXEC, live poll, signal 0, invalid args, EBADF, child signal and exit poll");
    return 0;
}
