# BakaSU Manual Hook — auditoria de patchpoints para Linux 3.18.140

## Revisão de driver e manager

- BakaSU: `5785bdb8091304322f597f67d50e0b79f9815cb2`
- APK esperado: manager 35253 / UAPI 6.
- A revisão antiga ligada ao sufixo do driver antigo era UAPI 5. O driver deve implementar UAPI 6; não basta falsificar release string.
- O alvo já tem `CONFIG_THREAD_INFO_IN_TASK=y`, `CONFIG_KALLSYMS=y`, `CONFIG_KALLSYMS_ALL=y`, `CONFIG_KEYS=y` e SELinux habilitado no `deen_defconfig`.

## Integração de fonte já realizada

A revisão BakaSU está ligada como submódulo Git no caminho raiz `KernelSU`, fixada no commit acima. `drivers/kernelsu` aponta para `../KernelSU/kernel`; `drivers/Kconfig` e `drivers/Makefile` incluem o diretório.

O workflow faz checkout recursivo e verifica SHA do submódulo. **Isso adiciona a fonte e a ligação de build, mas ainda não ativa o driver**: `CONFIG_KSU` permanece desativado no `deen_defconfig`.

## Hooks aplicados no kernel

### Execução

O alvo 3.18 não possui `execveat`/wrapper moderno correspondente. As entradas relevantes são `do_execve()` e `compat_do_execve()`, que convergem em `do_execve_common(struct filename *, struct user_arg_ptr, struct user_arg_ptr)`.

Os hooks foram colocados em `do_execve_common()`:
- pre-hook após validar `filename`, usando o sentinel legado `AT_FDCWD`;
- post-hook no caminho de sucesso e no caminho de erro, **antes** de `putname(filename)`.

O post-hook não deve ficar nos wrappers depois de `do_execve_common()`: essa função libera `filename` antes de retornar, e BakaSU consulta `filename->name` no pós-hook. A primeira implementação fora da função foi detectada e substituída antes de qualquer alegação de teste.

### Reboot / instalação do descriptor

Em `kernel/reboot.c`, o caminho com `magic1 == 0xDEADBEEF` é encaminhado para `ksu_handle_sys_reboot()` antes da checagem de `CAP_SYS_BOOT`. O restante das chamadas de reboot Linux mantém o fluxo original. A declaração comum ficou em `include/linux/ksu_hooks.h`.

## Hooks pendentes obrigatórios

O `manual_hook_check.mk` da revisão BakaSU exige estes marcadores para o caminho de Manual Hook:

| Arquivo do alvo | Hook exigido | Estado |
|---|---|---|
| `fs/exec.c` | `ksu_handle_execveat` | Aplicado em `do_execve_common`, nativo e compat convergem aqui |
| `kernel/reboot.c` | `ksu_handle_sys_reboot` | Aplicado antes da validação de capacidade |
| `fs/open.c` | `ksu_handle_faccessat` | Pendente |
| `fs/stat.c` | `ksu_handle_stat` | Pendente |
| `fs/stat.c` | `ksu_handle_newfstat_ret` | Pendente |
| `fs/stat.c` | `ksu_handle_fstat64_ret` | Pendente |

### Incompatibilidade específica de faccessat/stat

No BakaSU com `CONFIG_KSU_SUSFS`, os prototypes de `ksu_handle_faccessat()` e `ksu_handle_stat()` esperam `struct filename **`. No syscall 3.18, `faccessat` e stat recebem `const char __user *`; o código faz a resolução dentro de VFS legado, sem receber esse `struct filename **` do chamador.

Não fazer cast de `const char __user **` para `struct filename **`: são tipos e objetos diferentes. A adaptação deve preservar a resolução relativa a `dfd`, flags de lookup, erros, compat 32/64 bits e lifetime do nome. A alternativa é adicionar uma variante explícita de API legada no overlay BakaSU (user pointer) e chamar o handler antes de `user_path_at()`; confirmar que a mudança de nome é visível ao caminho VFS efetivamente usado.

### Hooks stat pós-preenchimento

`ksu_handle_newfstat_ret()` e `ksu_handle_fstat64_ret()` alteram a saída de stat, portanto devem ser chamados somente depois que o kernel preencher o `struct stat`/`stat64` correspondente e antes de copiar o resultado ao userspace. Cobrir `newfstatat`, `newfstat`, `stat64`, `lstat64` e `fstat64` aplicáveis nesta ABI.

## Compatibilização necessária no BakaSU

A Kconfig upstream coloca `KSU_MANUAL_HOOK` e `KSU_SUSFS` na mesma `choice`; e `kernel/core/init.c` usa `#if/#elif`, de modo que Manual Hook pode suprimir `susfs_init()` se ambos os símbolos forem forçados.

A adaptação deverá:
1. manter Manual Hook como a escolha do método de hooking;
2. mover `KSU_SUSFS` para uma opção booleana independente, preservando seus guards de feature;
3. no ramo Kbuild de Manual Hook, incluir também a validação `susfs_compat.mk` quando SUSFS estiver ligado;
4. chamar `susfs_init()` fora da cadeia exclusiva de seleção de hook, exatamente uma vez;
5. preservar os auto-hooks LSM/input habilitados no IKCONFIG antigo, verificando os seus contratos contra a árvore 3.18.

## Estado e gates

- [x] BakaSU 35253/UAPI 6 fixado como submódulo.
- [x] Kconfig/Makefile do kernel ligados ao diretório KernelSU.
- [x] Hooks de execve posicionados com lifetime correto.
- [x] Hook de reboot/instalação do descriptor.
- [ ] Hook compatível de faccessat.
- [ ] Hooks stat pre/post para todas as syscalls aplicáveis.
- [ ] Overlay BakaSU para Manual Hook + SUSFS independente.
- [ ] `CONFIG_KSU=y`, build ARM64 e verificação UAPI real.
- [ ] Testes de root grant, allowlist, daemon, SELinux e manager 35253 no Motorola One Deen.

Nenhuma compilação ou execução em dispositivo é declarada por este documento.
