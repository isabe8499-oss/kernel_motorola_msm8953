# Mimir Linux 3.18.140 — baseline de fontes e estado de integração

Este arquivo fixa as revisões de dependências e distingue código conectado, código compilado e código testado. SHA fixado não significa integração funcional.

## Repositório alvo

- Kernel: https://github.com/isabe8499-oss/kernel_motorola_msm8953
- Branch: `integration/bakasu-35253-susfs22-nomount`
- Alvo: Motorola One Deen / MSM8953 / ARM64 / Linux 3.18.140.

## Dependências fixadas

| Componente | Revisão | Estado |
|---|---|---|
| BakaSU | `5785bdb8091304322f597f67d50e0b79f9815cb2` | Submódulo conectado; UAPI 6; 4553 commits = manager versionCode 35253 |
| SUSFS | `4003ecf2d01c6d13fa8edf6c4f2607365738dc3d` | Fonte fixada; `susfs.h` declara v2.2.0; ainda não integrado ao kernel |
| NoMount | `bf1847f98fed382369c43bfd652cd93774b9b8e3` | Fonte v2.2.0/protocolo 22 fixada; ainda não integrado ao kernel |

## Evidências dos artefatos antigos

- ZIP antigo: `Kernel-MTONEDEEN-bakaSU+SUSFS-kernel 3.18.zip`
- SHA-256: `ff8fce5eed51335748f313a709dac89673e001abeb30f2a4b7d24d6509e8b282`
- APK BakaSU 35253/6: `BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk`
- SHA-256: `11a276b3ceb7e3102be14d5274fc472ed4ff919277db924c57009363628c85a`

O IKCONFIG recuperado do ZIP antigo contém simultaneamente `CONFIG_KSU_MANUAL_HOOK=y` e opções `CONFIG_KSU_SUSFS_*` ligadas. A imagem também contém nomes de rotinas SUSFS, inclusive open redirect e sus map. Isso prova a presença de código/configuração na imagem antiga, mas não recupera os patches locais.

## Estado atual por componente

### BakaSU

- Submódulo gitlink fixado no commit UAPI 6 correspondente ao APK 35253/6.
- `drivers/Kconfig` e `drivers/Makefile` ligados ao diretório `drivers/kernelsu`, symlink para `KernelSU/kernel`.
- `deen_defconfig` seleciona `CONFIG_KSU=y`, `CONFIG_KSU_MANUAL_HOOK=y` e opções automáticas de setuid/LSM/input.
- Hooks manuais adicionados em `fs/exec.c`, `fs/open.c`, `fs/stat.c` e `kernel/reboot.c`. O caminho compat de `execve` também foi instrumentado.
- O workflow valida o SHA do submódulo, a contagem 4553, e fixa build script, GCC e AnyKernel3 por SHA.
- **Ainda não compilado nem validado em runtime.** UAPI 6, driver fd, daemon e root grant continuam pendentes de build/teste.

### SUSFS 2.2.0

- A revisão upstream está fixada, mas os fontes e patches ainda não foram portados para o fork 3.18.140.
- O Kconfig upstream mistura o seletor de Inline Hook com o sinalizador de funcionalidade SUSFS. O binário antigo demonstra que a integração local permitia Manual Hook e SUSFS juntos.
- Próxima alteração: separar `KSU_SUSFS_INLINE_HOOK` (método de hook) de `KSU_SUSFS` (feature), manter Manual Hook, inicializar SUSFS independentemente do seletor e ajustar as condicionais de `sucompat`, `preinit` e `ksud_integration`.
- Não habilitar `CONFIG_KSU_SUSFS_*` antes de os fontes correspondentes estarem ligados ao build.

### NoMount 2.2.0

- Revisão e protocolo v22 fixados.
- A porta Linux 3.18 exige compatibilidade para `iterate_shared`, symlink `get_link/delayed_call`, `inode_lock`, xattr handlers, flags de dentry e RCU lifetime.
- `dir_emit()`, `iterate_dir()` e o callback legado `filldir_t` já existem neste fork; preservar também `dir_context::romnt`.
- Ainda não há fontes NoMount em `fs/`, entradas Kconfig/Makefile, build ou teste do protocolo 22.

## Critérios de aceitação

- [x] Checkout recursivo BakaSU fixado e verificado no workflow.
- [x] Build script, GCC e AnyKernel3 fixados por commit.
- [x] BakaSU Manual Hook conectado no Kconfig/Makefile e selecionado no defconfig.
- [x] Hooks de syscall obrigatórios identificados e inseridos no fonte.
- [ ] `make olddefconfig` confirma a configuração esperada.
- [ ] Kbuild passa `manual_hook_check.mk` e compila o driver ARM64.
- [ ] `KSU_IOCTL_GET_INFO` responde UAPI 6; manager e kernel reportam 6.
- [ ] Testes de root grant, daemon, perfis e instalação do descritor passam.
- [ ] SUSFS 2.2.0 integrado com Manual Hook e todos os recursos selecionados compilados/testados.
- [ ] NoMount v2.2.0 integrado, protocolo 22 validado e testes de concorrência passam.
- [ ] Build ARM64 reproduzível, boot image inspecionada e ZIP AnyKernel3 verificado.

Nenhuma compilação, inicialização em aparelho ou ZIP final é declarada nesta etapa.
