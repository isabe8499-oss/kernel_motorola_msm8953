# BakaSU Manual Hook — auditoria para Linux 3.18.140

## Revisão fixada

- Repositório: `Baka-SU/BakaSU`
- Commit imutável: `5785bdb8091304322f597f67d50e0b79f9815cb2`
- Manager correspondente: versionCode 35253, UAPI 6.
- O kernel 3.18.140 do fork já define `CONFIG_THREAD_INFO_IN_TASK=y`, `CONFIG_KALLSYMS=y`, `CONFIG_KALLSYMS_ALL=y`, `CONFIG_KEYS=y` e SELinux no `deen_defconfig`.

## Integração e overlay

O commit BakaSU está ligado como submódulo Git no caminho raiz `KernelSU`; `drivers/kernelsu` aponta para `../KernelSU/kernel`, e `drivers/Kconfig`/`drivers/Makefile` fazem a ligação ao build.

O script `scripts/apply-bakasu-318-compat.py` é executado pelo workflow após conferir o SHA do submódulo. Ele:
1. mantém `KSU_MANUAL_HOOK` como método de hook;
2. move `KSU_SUSFS` para uma opção independente, fora da `choice` de métodos;
3. chama `susfs_init()` também no caminho Manual Hook, sem deixar a ramificação `#elif` suprimi-la;
4. no ramo Manual Hook, executa `susfs_compat.mk` e exige `fs/susfs.c` e `include/linux/susfs.h` quando SUSFS for habilitado;
5. em Linux 3.18, define `KSU_COMPAT_LEGACY_USERPATH`, selecionando os prototypes de `faccessat/stat` que recebem `const char __user **`, mesmo quando SUSFS estiver ativo.

O overlay não ativa configuração por si só. `CONFIG_KSU` e `CONFIG_KSU_SUSFS` permanecem desligados até completar o port e compilar.

## Patchpoints do kernel já presentes

A conferência foi feita contra os arquivos desta branch:

| Arquivo | Chamada | Estado atual |
|---|---|---|
| `fs/exec.c` | `ksu_handle_execveat` | Presente no caminho comum a native/compat |
| `fs/exec.c` | `ksu_handle_post_execveat` | Presente no sucesso e no erro, antes de `putname(filename)` |
| `kernel/reboot.c` | `ksu_handle_sys_reboot` | Presente para `KSU_INSTALL_MAGIC1`, antes do teste normal de `CAP_SYS_BOOT` |
| `fs/open.c` | `ksu_handle_faccessat` | Já presente no `SYSCALL_DEFINE3(faccessat)` |
| `fs/stat.c` | `ksu_handle_stat` | Já presente em `newfstatat` e `fstatat64` |
| `fs/stat.c` | `ksu_handle_newfstat_ret` | Já presente em `newfstat`; agora chamado somente se a cópia do stat tiver sucesso |
| `fs/stat.c` | `ksu_handle_fstat64_ret` | Já presente em `fstat64`; agora chamado somente se a cópia do stat tiver sucesso |

### Lifetime do hook de exec

O alvo 3.18 não tem o wrapper moderno de `execveat`; `do_execve()` e `compat_do_execve()` convergem em `do_execve_common()`.

Os hooks são executados dentro de `do_execve_common()`. O pós-hook consulta `filename->name`; por isso ele é chamado nos caminhos de sucesso e erro antes de `putname(filename)`. Uma primeira implementação nos wrappers depois de `do_execve_common()` foi descartada porque acessaria `struct filename` depois de liberada.

### Reboot / instalação do descriptor

O syscall handler encaminha `magic1 == KSU_INSTALL_MAGIC1` para `ksu_handle_sys_reboot()`; a constante local é `((int)0xDEADBEEF)`, mantendo o padrão de bits da UAPI sem warning de signedness. O header compartilhado declara as funções de hook sob o guard Manual Hook.

### ABI de faccessat/stat com SUSFS

O BakaSU upstream usa `struct filename **` quando `CONFIG_KSU_SUSFS` está ligado. Isso não corresponde às syscalls Linux 3.18 deste fork, que recebem ponteiros de usuário `const char __user *`. Não fazer cast entre os dois tipos: apontam para objetos diferentes e têm lifetimes diferentes.

O overlay seleciona as variantes legadas de `ksu_handle_faccessat()` e `ksu_handle_stat()`, que substituem o ponteiro de usuário para redirecionar `/system/bin/su` para `/system/bin/sh`. Os parâmetros de `dfd` e flags permanecem na syscall original; a resolução continua sendo feita pelo VFS 3.18.

## Pendências antes de ativar

- [ ] Integrar e adaptar o código SUSFS 2.2.0 fixado; só então ativar `CONFIG_KSU_SUSFS=y`.
- [ ] Conferir o conjunto de chamadas `newfstatat/fstatat64` na ABI de 32/64 bits do aparelho e validar os eventos/saídas de stat.
- [ ] Confirmar se a ROM usa também syscalls legadas `stat/lstat/stat64/lstat64` sem passar por `fstatat64`; adicionar hooks adicionais somente se necessário e preservando `dfd`, flags e compat.
- [ ] Confirmar os auto-hooks LSM/input com as estruturas efetivas de 3.18.
- [ ] Ativar `CONFIG_KSU=y`, `CONFIG_KSU_MANUAL_HOOK=y` e auto-hook options depois que o port estiver pronto.
- [ ] Compilar ARM64, testar `KSU_IOCTL_GET_INFO`/UAPI 6, root grant, allowlist, daemon e manager 35253 no Motorola One Deen.

Nenhuma compilação, inicialização no aparelho ou comunicação UAPI funcional é declarada neste estágio.
