#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <poll.h>
#include <signal.h>

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif
#ifndef SYS_pidfd_send_signal
#define SYS_pidfd_send_signal 424
#endif

int main(void)
{
    int fd = (int)syscall(SYS_pidfd_open, getpid(), 0);
    if (fd < 0) {
        perror("pidfd_open");
        return errno == ENOSYS ? 2 : 1;
    }

    struct pollfd pfd = { .fd = fd, .events = POLLIN };
    int ready = poll(&pfd, 1, 0);
    if (ready != 0) {
        fprintf(stderr, "unexpected poll result for live self: %d (revents=0x%x)\n",
                ready, pfd.revents);
        close(fd);
        return 3;
    }

    if (syscall(SYS_pidfd_send_signal, fd, 0, NULL, 0) < 0) {
        perror("pidfd_send_signal(sig=0)");
        close(fd);
        return 4;
    }

    printf("pidfd_open OK: fd=%d; poll(live self)=0; pidfd_send_signal(sig=0)=OK\n", fd);
    close(fd);
    return 0;
}
