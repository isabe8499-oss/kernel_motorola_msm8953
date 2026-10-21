/*
 * Minimal runtime check for the pidfd_open syscall backport.
 *
 * Build on-device or with an AArch64 cross compiler:
 *   clang -Wall -Wextra -O2 tools/pidfd_open_test.c -o pidfd_open_test
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>

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

	printf("pidfd_open OK: fd=%d, FD_CLOEXEC set\n", fd);
	close(fd);
	return 0;
}
