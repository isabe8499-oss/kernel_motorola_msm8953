/*
 * Minimal runtime check for the pidfd_open syscall backport.
 *
 * Build on-device or with an AArch64 cross compiler:
 *   clang -Wall -Wextra -O2 tools/pidfd_open_test.c -o pidfd_open_test
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>

#ifndef SYS_pidfd_send_signal
#define SYS_pidfd_send_signal 424
#endif
#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif

int main(void)
{
	int fd = (int)syscall(SYS_pidfd_open, getpid(), 0U);
	int fdflags;

	if (fd < 0) {
		int saved_errno = errno;
		fprintf(stderr, "pidfd_open failed: errno=%d (%s)\n",
			saved_errno, strerror(saved_errno));
		return saved_errno == ENOSYS ? 2 : 1;
	}

	if (syscall(SYS_pidfd_send_signal, fd, 0, NULL, 0U) < 0) {
		perror("pidfd_send_signal(signal=0)");
		close(fd);
		return 1;
	}

	fdflags = fcntl(fd, F_GETFD);
	if (fdflags < 0) {
		perror("fcntl(F_GETFD)");
		close(fd);
		return 1;
	}
	if (!(fdflags & FD_CLOEXEC)) {
		fprintf(stderr, "pidfd_open returned fd without FD_CLOEXEC\n");
		close(fd);
		return 1;
	}

	printf("pidfd_open OK: fd=%d, FD_CLOEXEC set; pidfd_send_signal(signal=0) OK\n", fd);
	close(fd);

	/* A closed pidfd must not be accepted as a process handle. */
	if (syscall(SYS_pidfd_send_signal, fd, 0, NULL, 0U) != -1 || errno != EBADF) {
		fprintf(stderr, "pidfd_send_signal on closed fd should fail with EBADF\n");
		return 1;
	}
	return 0;
}
