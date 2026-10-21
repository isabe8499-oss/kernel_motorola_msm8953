/*
 * Minimal pidfd_open smoke test for the Linux 3.18 arm64 backport.
 * Build with: aarch64-linux-gnu-gcc -Wall -Wextra -O2 -o pidfd_open_test pidfd_open_test.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif

int main(void)
{
	int fd = syscall(SYS_pidfd_open, getpid(), 0);

	if (fd < 0) {
		perror("pidfd_open");
		return errno == ENOSYS ? 2 : 1;
	}

	printf("pidfd_open OK: fd=%d\n", fd);
	close(fd);
	return 0;
}
