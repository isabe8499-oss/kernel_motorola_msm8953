# BakaSU 35253/6 — requisito UAPI e integração Manual Hook no Linux 3.18.140

## Artefatos e revisões fixadas

- APK: `BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk`
- APK SHA-256: `11a276b3ceb7e3102be14d5274fc472ed4ff919277db924c57009363628c85a`
- BakaSU submodule: `5785bdb8091304322f597f67d50e0b79f9815cb2`
- Esse commit é o HEAD de `main`, declara UAPI 6 e tem 4553 commits alcançáveis.
- Fórmula do manager: `30000 + git rev-list --count HEAD + 700`; `30000 + 4553 + 700 = 35253`.
- O workflow verifica o SHA do submódulo e exige contagem 4553, para não gerar driver com versão baseada em clone raso.

## Requisito UAPI confirmado

A biblioteca nativa do APK consulta versão do kernel, UAPI do kernel, UAPI do manager, versão completa e tipo de hook. Ela procura o descritor `[ksu_driver]` e consulta o driver por ioctl.

O manager considera o kernel full featured somente quando:

```kotlin
isManager && kernelUAPIVersion == managerUAPIVersion
```

Logo, o driver precisa responder UAPI 6 em `KSU_IOCTL_GET_INFO`. Alterar apenas o texto da versão ou o versionCode não implementa os ioctls ausentes.

A revisão antiga `7c383cfeef3a2ac450f2f1273dae74bd50356d31`, associada ao sufixo `7c383cfe` do driver antigo, declara UAPI 5. Ela não satisfaz o estado full featured do manager UAPI 6.

## Integração do código no kernel 3.18.140

O submódulo foi conectado por `.gitmodules`, gitlink fixado, symlink `drivers/kernelsu -> ../KernelSU/kernel`, `source "drivers/kernelsu/Kconfig"` e `obj-$(CONFIG_KSU) += kernelsu/`.

O `deen_defconfig` agora contém:

- `CONFIG_KSU=y`
- `CONFIG_KSU_MULTI_MANAGER_SUPPORT=y`
- `CONFIG_KSU_MANUAL_HOOK=y`
- `CONFIG_KSU_MANUAL_HOOK_AUTO_SETUID_HOOK=y`
- `CONFIG_KSU_MANUAL_HOOK_AUTO_INITRC_HOOK=y`
- `CONFIG_KSU_MANUAL_HOOK_AUTO_INPUT_HOOK=y`

Os pontos de integração manual adicionados/verificados são:

| Arquivo | Hook |
|---|---|
| `fs/exec.c` | `ksu_handle_execveat` + `ksu_handle_post_execveat` em `do_execve` e `compat_do_execve` |
| `fs/open.c` | `ksu_handle_faccessat` em `SYSCALL_DEFINE3(faccessat)`, após as declarações locais |
| `fs/stat.c` | `ksu_handle_stat` em `newfstatat` e `fstatat64` |
| `fs/stat.c` | `ksu_handle_newfstat_ret` em `newfstat` |
| `fs/stat.c` | `ksu_handle_fstat64_ret` em `fstat64` |
| `kernel/reboot.c` | `ksu_handle_sys_reboot` no caminho de instalação do descritor |

O caminho de `execve` preserva o pós-hook após o retorno de `do_execve_common`, e o wrapper compatível também foi instrumentado para 32-bit/32-on-64. As opções automáticas de LSM e input permanecem habilitadas, evitando duplicar hooks manuais onde o BakaSU os instala automaticamente.

A árvore já tem `CONFIG_KEYS=y`, `CONFIG_KALLSYMS_ALL=y` e SELinux habilitado no defconfig; isso atende dependências importantes do driver e evita a etapa de exportação estática que o Kbuild usa quando `KALLSYMS_ALL` está desligado.

## Conflito de arquitetura SUSFS ainda pendente

No Kconfig upstream fixado, `KSU_MANUAL_HOOK` e `KSU_SUSFS` são opções mutuamente exclusivas na mesma `choice`. O código também usa `CONFIG_KSU_SUSFS` tanto para selecionar o modo Inline Hook quanto para compilar funcionalidades SUSFS.

O ZIP antigo é evidência de uma customização que permitia simultaneamente `CONFIG_KSU_MANUAL_HOOK=y` e `CONFIG_KSU_SUSFS=y`; o IKCONFIG e as strings da imagem confirmam isso, mas não recuperam os patches locais.

O overlay `scripts/apply-bakasu-318-compat.py`, executado pelo workflow, move `KSU_SUSFS` para fora da `choice` como feature independente, mantém `KSU_MANUAL_HOOK` como método selecionado e chama `susfs_init()` dentro do caminho Manual Hook. Ele também força a ABI de ponteiro de usuário legado em `faccessat/stat`, compatível com os syscalls do 3.18, e prioriza Manual Hook no dispatcher initrc/input. A opção SUSFS continua desligada no `deen_defconfig` até o core SUSFS e os hooks do kernel estarem integrados. O `sucompat.h` do BakaSU passa a exigir `susfs_is_current_proc_no_su()` quando a feature for ligada; a fonte SUSFS 2.2.0 não fornece esse helper, então será adicionado um shim local `TIF_PROC_NO_SU` sem alterar a versão upstream.

## Estado e critérios de aceitação

**Código-fonte conectado:** os hooks obrigatórios de Manual Hook foram inseridos e o defconfig seleciona BakaSU. O workflow também valida o checkout fixado e o número de commits.

**Ainda sem build/boot:** não foi executada uma compilação ARM64 depois dessas alterações. Não há confirmação runtime de UAPI 6, instalação do descritor, root grant, daemon ou boot.

- [ ] Executar `make olddefconfig` e confirmar `CONFIG_KSU=y` + `CONFIG_KSU_MANUAL_HOOK=y`.
- [ ] Passar o `manual_hook_check.mk` durante o Kbuild.
- [ ] Compilar ARM64 e resolver erros/warnings.
- [ ] Confirmar `KSU_IOCTL_GET_INFO`: kernel UAPI 6 e manager UAPI 6.
- [ ] Confirmar `isFullFeatured() == true`, root grant e comunicação com daemon.
- [ ] Integrar o core SUSFS 2.2.0 e o shim `susfs_is_current_proc_no_su()` mantendo Manual Hook.
- [ ] Testar no Motorola One Deen e preservar caminho de recuperação.

Este relatório separa o que já está conectado no fonte do que ainda depende de compilação e teste. Não declara build funcional nem ZIP pronto.
