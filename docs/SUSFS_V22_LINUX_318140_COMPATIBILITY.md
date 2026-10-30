# SUSFS v2.2.0 — compatibilidade e pontos de backport para Linux 3.18.140

## Fonte fixada

- Repositório: https://gitlab.com/simonpunk/susfs4ksu
- Commit: `4003ecf2d01c6d13fa8edf6c4f2607365738dc3d`
- Arquivo de versão: `kernel_patches/include/linux/susfs.h`
- Versão declarada no próprio header: `SUSFS_VERSION "v2.2.0"`
- Fonte principal: `kernel_patches/fs/susfs.c`

Não usar o commit `86114db0` encontrado em referências antigas: ele declara SUSFS v2.1.0, não v2.2.0.

## Interfaces já presentes no fork 3.18.140

A comparação foi feita contra os headers efetivos do fork `kernel_motorola_msm8953`, branch `integration/bakasu-35253-susfs22-nomount`.

- `strscpy()` está implementada em `lib/string.c` e declarada em `include/linux/string.h`.
- `DEFINE_STATIC_SRCU`, `srcu_read_lock()` e `srcu_read_unlock()` existem.
- `utsname()`, `current_uid().val`, `d_backing_inode()`, `path_equal()`, `FUSE_SUPER_MAGIC` e `get_fuse_inode()` existem.
- O `deen_defconfig` já define `CONFIG_THREAD_INFO_IN_TASK=y`; a árvore ARM64 é 64-bit.
- O `struct thread_info` do alvo usa campo `unsigned long flags`; seus TIFs declarados ocupam os bits 0–24. Os bits superiores usados pelo SUSFS/BakaSU (33, 61 e 62) não colidem com esses TIFs existentes no header analisado.
- `include/linux/pagemap.h` define os flags de mapping 26–30 (`AS_EIO` até `AS_EXITING`); os bits 33–39 usados pelo SUSFS para flags privadas não coincidem com os flags declarados nessa versão, em ARM64 onde `unsigned long` tem 64 bits.
- `include/linux/bitops.h` fornece as macros de bit relevantes, mas `include/linux/bits.h` do SUSFS não existe no alvo.

Esses pontos evitam criar compatibilidade redundante, mas não substituem a revisão de todos os pontos de chamada VFS/proc/mm.

## Adaptações necessárias

1. **Headers de bits:** trocar o include moderno `<linux/bits.h>` pelo header 3.18 apropriado (`<linux/bitops.h>`) e confirmar todas as macros efetivamente usadas.
2. **Static keys:** o alvo possui `struct static_key`, `STATIC_KEY_INIT_TRUE/FALSE`, `static_key_true/false/enabled()` e `static_key_slow_inc/dec()`; não expõe a API moderna `DEFINE_STATIC_KEY_TRUE/FALSE` nem `static_branch_enable/disable/likely/unlikely`. A camada 3.18 deve mapear os predicados para `static_key_true/false` e implementar transições enable/disable idempotentes. Não substituir cegamente enable/disable por inc/dec: a API antiga é referenciada por contagem, enquanto os comandos SUSFS podem ser repetidos. Proteger transições concorrentes e preservar os estados iniciais TRUE/FALSE.
3. **Namei:** o `struct nameidata` do alvo não contém o campo `state` usado pelos patches modernos. O backport precisa definir onde armazenar o estado de lookup/open, garantir que os bits de `LOOKUP_* ` não colidam com as flags legadas e atualizar todos os inicializadores/usos de `nameidata`.
4. **VFS/UID:** selecionar as assinaturas antigas por `LINUX_VERSION_CODE`. O fonte SUSFS já contém ramos de compatibilidade antes de 5.15/6.6 para UID e inode; preservar o ramo legado `i_uid.val` e a assinatura `susfs_is_inode_sus_path(struct inode *)`.
5. **fsnotify:** o monitor de `/data/media/0/Android` precisa ser compilado contra a API fsnotify exata deste kernel. Revisar criação/registro de group, marca de inode, callback, SRCU e o cleanup deferred-work; não copiar uma assinatura moderna sem adaptação.
6. **Inicialização:** `susfs_init()` deve ser chamada uma única vez no caminho built-in. A configuração BakaSU upstream precisa ser ajustada para que Manual Hook não suprima essa chamada.

## Recursos e pontos de chamada a portar

| Recurso | Rotinas do SUSFS 2.2.0 | Áreas do kernel 3.18 que precisam de revisão |
|---|---|---|
| SUS_PATH | `susfs_add_sus_path`, `susfs_add_sus_path_loop`, `susfs_is_inode_sus_path` | namei/path lookup, verificação do inode de backing/FUSE e operações que enumeram diretórios |
| SUS_MOUNT | controle de mounts ocultos por processo | `fs/proc_namespace.c`, geração de `mounts`/`mountinfo`, callbacks de seq_file |
| SUS_KSTAT | `susfs_sus_kstat_spoof_generic_fillattr`, `susfs_sus_kstat_spoof_show_map_vma` | `generic_fillattr`/stat e `show_map_vma` |
| SPOOF_UNAME | `susfs_spoof_uname` | `sys_newuname`/cópia da estrutura uts para userspace |
| SPOOF_CMDLINE_OR_BOOTCONFIG | `susfs_spoof_cmdline_or_bootconfig` | `/proc/cmdline`; bootconfig só se existir no alvo |
| OPEN_REDIRECT | `susfs_open_redirect_spoof_do_sys_openat`, spoof de readlink, statfs, seq e maps | `fs/open.c`, readlink/proc readlink, `fs/statfs.c`, seq de mount e `fs/proc/task_mmu.c` |
| SUS_MAP | `susfs_add_sus_map` e flag `AS_FLAGS_SUS_MAP` | `show_map_vma` e emissão de `/proc/<pid>/maps` |
| Logging/AVC | enable/disable de static keys | handlers de logging/SELinux e static-key compat |

A enumeração acima indica os pontos de integração necessários; não afirma que eles já foram modificados neste fork. O nome exato dos arquivos/pontos de chamada deve ser fechado no patch de backport do 3.18 antes de ativar cada opção Kconfig.

## Evidência do kernel antigo

O ZIP antigo contém no IKCONFIG `CONFIG_KSU_SUSFS=y` e os símbolos de path, mount, kstat, spoof uname, spoof cmdline, open redirect e sus map. A imagem contém nomes de funções correspondentes. Isso valida o objetivo de reconstrução, mas não recupera os patches privados que adicionaram os hooks ao kernel 3.18.

## Estado da porta

- [x] Revisão de fonte fixada e versão 2.2.0 confirmada.
- [x] Inventário das APIs 3.18 que já existem e das que faltam.
- [x] Comparação inicial de bitmaps de mapping e thread flags.
- [ ] Camada de compatibilidade de static keys e nameidata.
- [ ] Portar/compilar `fs/susfs.c` e header.
- [ ] Ligar os pontos de chamada de cada recurso ao VFS/proc/mm 3.18.
- [ ] Separar `CONFIG_KSU_SUSFS` do seletor Manual Hook no overlay BakaSU.
- [ ] Build ARM64, runtime tests, stress RCU/SRCU e testes no dispositivo.

**Não habilitar `CONFIG_KSU_SUSFS_*` no defconfig antes de concluir esses itens.** O fonte ainda não foi integrado/compilado nesta branch.
