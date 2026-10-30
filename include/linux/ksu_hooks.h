#ifndef _LINUX_KSU_HOOKS_H
#define _LINUX_KSU_HOOKS_H

#include <linux/types.h>
#include <linux/uaccess.h>

struct filename;

/* BakaSU UAPI reboot hand-off magic, kept in sync with uapi/supercall.h. */
#define KSU_INSTALL_MAGIC1 0xDEADBEEF

int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
		void *argv, void *envp, int *flags);
int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr,
		void *argv, void *envp, int *flags, int *retval);
int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
		void __user **arg);

#endif /* _LINUX_KSU_HOOKS_H */
