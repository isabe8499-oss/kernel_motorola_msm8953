# SUSFS v2.2.0 — auditoria de porta para Linux 3.18.140

## Fonte upstream fixada

- Repositório: https://gitlab.com/simonpunk/susfs4ksu
- Commit: `4003ecf2d01c6d13fa8edf6c4f2607365738dc3d`
- O submódulo `SUSFS` na raiz do kernel aponta para esse commit.
- `kernel_patches/include/linux/susfs.h` declara `SUSFS_VERSION "v2.2.0"`.
- `kernel_patches/include/linux/susfs.h` define a variante `NON-GKI` para kernels anteriores a 5.0.
- Fonte principal: `kernel_patches/fs/susfs.c`, `kernel_patches/include/linux/susfs.h`, `kernel_patches/include/linux/susfs_def.h`.
- O arquivo `50_add_susfs_in_gki-android12-5.10.patch` é especificamente para GKI 5.10. **Não aplicar esse patch diretamente ao kernel 3.18.140.**

## Recursos exigidos pelo binário antigo

O IKCONFIG extraído de `Kernel-MTONEDEEN-bakaSU+SUSFS-kernel 3.18.zip` confirma estes recursos:

- `CONFIG_KSU_SUSFS_SUS_PATH`
- `CONFIG_KSU_SUSFS_SUS_MOUNT`
- `CONFIG_KSU_SUSFS_SUS_KSTAT`
- `CONFIG_KSU_SUSFS_SPOOF_UNAME`
- `CONFIG_KSU_SUSFS_ENABLE_LOG`
- `CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS`
- `CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG`
- `CONFIG_KSU_SUSFS_OPEN_REDIRECT`
- `CONFIG_KSU_SUSFS_SUS_MAP`

O port deve preservar esse conjunto. Não reduzir recursos apenas porque o patch upstream principal tem alvo GKI mais novo.

## Compatibilidade já confirmada no fork 3.18.140

| API/estrutura | Estado no 3.18.140 | Ação |
|---|---|---|
| `strscpy()` | Presente | Reutilizar |
| `DEFINE_STATIC_SRCU` | Presente | Reutilizar |
| `d_backing_inode()` | Presente | Reutilizar |
| `get_fuse_inode()` | Presente em `fs/fuse/fuse_i.h` | Reutilizar |
| `current_uid()` / `kuid_t.val` | Presente | Reutilizar |
| `ida_get_new_above()` / `ida_remove()` | Presentes | Usar API legada |
| `vfs_kern_mount()` | Presente | Reutilizar |
| `mm->mmap_sem` | Presente | Usar; não usar `mmap_lock` |
| `fsnotify_ops::handle_event` | Presente | Callback legado compatível |
| `iterate_dir()` / `dir_emit()` | Presentes | Reutilizar com callbacks legados |
| `generic_readlink()` | Presente | Hookar aqui; não há `vfs_readlink()` moderno |
| `inode->i_mutex` | Presente | Usar em vez de `inode_lock()` |

## Incompatibilidades que exigem porta explícita

1. **Static keys.** O SUSFS 2.2.0 usa `DEFINE_STATIC_KEY_TRUE/FALSE`, `static_branch_likely`, `static_branch_enable` e `static_branch_disable`. O 3.18 já tem `STATIC_KEY_INIT_TRUE/FALSE`, `static_key_true/false`, `static_key_enabled` e `static_key_slow_inc/dec`, mas não os nomes modernos. Adicionar macros compatíveis para inicialização/leitura. Implementar enable/disable com mutex e checagem de `static_key_enabled()`: o comando de log chama enable/disable sem checar o estado, então mapear diretamente para slow_inc/slow_dec vazaria referências após toggles repetidos.
2. **Header bits.** `linux/bits.h` não existe nesta árvore. O 3.18 já fornece `BIT()` e `GENMASK()` em `linux/bitops.h`; adaptar o include do `susfs_def.h`.
3. **Nameidata.** `struct nameidata` do 3.18 não possui `state`. SUSFS SUS_PATH usa `ND_STATE_LOOKUP_LAST` e `ND_STATE_OPEN_LAST`. Adicionar campo `state` condicionado à feature e inicializá-lo em `set_nameidata()`; não reutilizar `flags` sem preservar os bits LOOKUP existentes.
4. **filename_lookup.** A função existe em `fs/namei.c`, mas é `static` e usa assinatura antiga: `filename_lookup(int dfd, struct filename *name, unsigned int flags, struct nameidata *nd)`. Torná-la visível para os call sites SUSFS e declarar a assinatura exata em `fs/internal.h`; não copiar a assinatura de 4.9/5.10.
5. **Path lookup.** O `lookup_slow()` do 3.18 usa `mutex_lock(&inode->i_mutex)` e `__lookup_hash()`; não usa o fluxo mais novo `inode_lock_shared()`/`d_alloc_parallel()`. Portar SUS_PATH para o algoritmo antigo, incluindo o caminho RCU de `lookup_fast()` e a repetição com qstr sentinela, sem deixar dentry em estado `in_lookup`.
6. **Readdir.** `struct dir_context` usa `filldir_t actor` com primeiro argumento `void *`, e este fork tem `ctx->romnt`. Os callbacks `fillonedir/filldir/filldir64` também recebem `void *`. A porta deve obter o inode com o superblock da pasta, chamar `susfs_is_inode_sus_path()`, equilibrar `ilookup()/iput()` e preservar `romnt` e a semântica existente de ocultar `su`.
7. **Kstat.** O `struct kstat` do 3.18 não tem o marcador `result_mask` usado pelo patch GKI. Seguir o padrão de compatibilidade usado no port 4.9: manter marcador local em `vfs_getattr_nosec()` e fazer a consulta SUSFS correspondente em `statfs` sem depender do campo inexistente.
8. **Symlink/readlink.** O 3.18 usa `follow_link()`, `put_link()` e `nameidata`; o caminho de leitura pública é `generic_readlink()`. Não usar `get_link()`/ `delayed_call`.
9. **Procfs/mm.** Usar `mmap_sem`, `show_map_vma()`, `show_smap()` e `pagemap_read()` existentes. Não copiar hooks para `smaps_rollup` ou bootconfig que não existem no 3.18; spoof de cmdline deve atuar em `fs/proc/cmdline.c` sobre `saved_command_line`.
10. **Open redirect.** Adaptar os pontos de entrada do 3.18 (`do_filp_open()`, `path_openat()`, `do_last()`, `generic_readlink()`, `proc_pid_get_link()`, `show_map_vma()`) ao invés de copiar os hooks pré-open do GKI.
11. **KSU hooks duplicados.** O port 4.9/Inline Hook adiciona chamadas para `ksu_handle_sys_read`, `ksu_handle_setresuid`, `ksu_handle_vfs_fstat`, `ksu_handle_sys_reboot` e input hooks. Nesta branch o método escolhido é BakaSU Manual Hook, com LSM/input automáticos e hooks manuais já instalados. Não adicionar chamadas duplicadas: condicionar os hooks Inline Hook ao seletor Inline Hook, preservando os hooks Manual Hook existentes.


## Compatibilidade SUSFS 2.2.0 com o BakaSU 35253/6

- O `sucompat.h` do BakaSU UAPI 6 usa `susfs_is_current_proc_no_su()` quando `CONFIG_KSU_SUSFS` está habilitado. O `susfs_def.h` oficial v2.2.0 não declara esse helper nem `TIF_PROC_NO_SU`; o helper aparece em versões posteriores. A porta local precisa acrescentar o bit livre `TIF_PROC_NO_SU 34` e os helpers `susfs_is_current_proc_no_su`, `susfs_set_current_proc_no_su` e `susfs_clear_current_proc_no_su`, sem alterar `SUSFS_VERSION`.
- O `susfs.c` v2.2.0 usa `fsnotify_ops.handle_inode_event` com callback `(mark, mask, inode, dir, qstr, cookie)`. O 3.18 só tem `fsnotify_ops.handle_event` com `(group, inode, inode_mark, vfsmount_mark, mask, data, data_type, file_name, cookie)`. Adicionar um adaptador que construa `qstr` a partir de `file_name` e encaminhe para o handler SUSFS legado. O port 4.9/2.3.0 tem um exemplo dessa ponte; usar apenas como referência de API, não como fonte da versão.
- O `fsnotify_alloc_group(&fsnotify_ops)` sem flags já é o caminho usado pelo 3.18 e pelo ramo legado do SUSFS; manter essa assinatura.
## Bug de bitmask encontrado na fonte 2.2.0

Em `susfs.h`, a definição de `KSTAT_SPOOF_CTIME_TV_SEC` aparece como:

```c
#define KSTAT_SPOOF_CTIME_TV_SEC (1 < 8)
```

Isso avalia para `1`, colidindo com o bit `KSTAT_SPOOF_INO`. A porta local deve corrigir para `(1 << 8)` e manter a mesma definição compartilhada com o userspace/CLI, para não ativar spoof de campo errado.

## Referência de porting antigo

O repositório `wxx9248/susfs4ksu` contém uma porta SUSFS 2.3.0 para Linux 4.9. Ela é útil apenas como referência de adaptação VFS antiga (por exemplo `mmap_sem`, `vfs_kern_mount`, `ida_get_new_above`, `generic_readlink` e `kstat` sem `result_mask`). Não copiar sua versão 2.3.0 para esta branch: a fonte de produção continua fixada em SUSFS 2.2.0.

## Plano de integração

1. Copiar os três arquivos core da subárvore SUSFS fixada para `fs/susfs.c` e `include/linux/susfs*.h` durante o build.
2. Aplicar patch local Linux 3.18 para static keys, bits, nameidata, filename_lookup e VFS/proc/mm hooks.
3. Adicionar `fs/susfs.o`, Kconfig e chamada de inicialização sem substituir BakaSU Manual Hook.
4. Separar `KSU_SUSFS` (feature) de `KSU_SUSFS_INLINE_HOOK` (método de hook), preservando a ABI BakaSU UAPI 6.
5. Habilitar exatamente os recursos presentes no IKCONFIG antigo e compilar.
6. Testar cada recurso isoladamente e em conjunto; depois validar boot e runtime no Motorola One Deen.

## Estado

- [x] SUSFS v2.2.0 fixado como submódulo Git.
- [x] Workflow valida SHA e existência dos três arquivos core.
- [ ] Core copiado/ligado ao Kbuild.
- [ ] Port Linux 3.18 concluído.
- [ ] Kconfig coexistindo com BakaSU Manual Hook.
- [ ] Build ARM64 concluído.
- [ ] Recursos funcionais validados no dispositivo.

Este documento é auditoria de compatibilidade, não declaração de integração funcional.
