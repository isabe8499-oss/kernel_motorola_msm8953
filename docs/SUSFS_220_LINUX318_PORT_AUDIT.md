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

1. **Static keys.** O binário antigo confirma `# CONFIG_JUMP_LABEL is not set`. Isso não impede SUSFS: o `jump_label.h` 3.18 tem fallback atômico para `static_key_true/false`, `static_key_enabled` e `static_key_slow_inc/dec`. O shim de staging adiciona os nomes modernos e serializa enable/disable com mutex + checagem de estado, evitando vazamento de referências em toggles repetidos. Não habilitar `CONFIG_JUMP_LABEL` artificialmente.
2. **Header bits.** `linux/bits.h` não existe nesta árvore. O 3.18 já fornece `BIT()` e `GENMASK()` em `linux/bitops.h`; adaptar o include do `susfs_def.h`.
3. **Nameidata.** `struct nameidata` do 3.18 não possui `state`. O campo `state` já foi adicionado sob `CONFIG_KSU_SUSFS` e é inicializado em `path_init()` (o 3.18 não tem `set_nameidata()`). `ND_STATE_LOOKUP_LAST` e `ND_STATE_OPEN_LAST` permanecem separados de `flags`.
4. **filename_lookup.** A função com assinatura 3.18 (`filename_lookup(int dfd, struct filename *name, unsigned int flags, struct nameidata *nd)`) já foi tornada global e declarada em `fs/internal.h` para os call sites SUSFS.
5. **Path lookup.** O `lookup_slow()` do 3.18 usa `mutex_lock(&inode->i_mutex)` e `__lookup_hash()`; não usa `inode_lock_shared()`/`d_alloc_parallel()`. Os pontos SUS_PATH já foram adicionados sob `CONFIG_KSU_SUSFS_SUS_PATH` em `lookup_dcache()`, `__lookup_hash()`, nos caminhos RCU/ref de `lookup_fast()`, `walk_component()`, `link_path_walk()`, `lookup_last()`, `lookup_open()` e `do_last()`. Ainda precisam de compilação e testes de lookup concorrente.
6. **Readdir.** `struct dir_context` usa `filldir_t actor` com primeiro argumento `void *`, e este fork tem `ctx->romnt`. Os callbacks `fillonedir/filldir/filldir64` também recebem `void *`. A porta deve obter o inode com o superblock da pasta, chamar `susfs_is_inode_sus_path()`, equilibrar `ilookup()/iput()` e preservar `romnt` e a semântica existente de ocultar `su`.
7. **Kstat.** O `struct kstat` do 3.18 não tem o marcador `result_mask` usado pelo patch GKI. Seguir o padrão de compatibilidade usado no port 4.9: manter marcador local em `vfs_getattr_nosec()` e fazer a consulta SUSFS correspondente em `statfs` sem depender do campo inexistente.
8. **Symlink/readlink.** O 3.18 usa `follow_link()`, `put_link()` e `nameidata`; o hook público de spoof readlink já foi adicionado em `generic_readlink()` sob `CONFIG_KSU_SUSFS_OPEN_REDIRECT`. Não usar `get_link()`/`delayed_call`.
9. **Procfs/mm.** Usar `mmap_sem`, `show_map_vma()`, `show_smap()` e `pagemap_read()` existentes. Não copiar hooks para `smaps_rollup` ou bootconfig que não existem no 3.18; spoof de cmdline deve atuar em `fs/proc/cmdline.c` sobre `saved_command_line`.
10. **Open redirect.** Os hooks de entrada em `do_filp_open()` e `generic_readlink()` já foram adicionados sob `CONFIG_KSU_SUSFS_OPEN_REDIRECT`; o restante ainda precisa ser portado para `proc_pid_get_link()`, `show_map_vma()` e `statfs`.
11. **KSU hooks duplicados.** O port 4.9/Inline Hook adiciona chamadas para `ksu_handle_sys_read`, `ksu_handle_setresuid`, `ksu_handle_vfs_fstat`, `ksu_handle_sys_reboot` e input hooks. O overlay `scripts/apply-bakasu-318-compat.py` mantém BakaSU Manual Hook como método e separa `KSU_SUSFS` como feature; também prioriza Manual Hook no runtime initrc/input. Não adicionar chamadas Inline Hook duplicadas.


## Compatibilidade SUSFS 2.2.0 com o BakaSU 35253/6

- O `sucompat.h` do BakaSU UAPI 6 usa `susfs_is_current_proc_no_su()` quando `CONFIG_KSU_SUSFS` está habilitado. O `susfs_def.h` oficial v2.2.0 não declara esse helper nem `TIF_PROC_NO_SU`; o helper aparece em versões posteriores. A porta local precisa acrescentar o bit livre `TIF_PROC_NO_SU 34` e os helpers `susfs_is_current_proc_no_su`, `susfs_set_current_proc_no_su` e `susfs_clear_current_proc_no_su`, sem alterar `SUSFS_VERSION`.
- O `susfs.c` v2.2.0 usa `fsnotify_ops.handle_inode_event` com callback `(mark, mask, inode, dir, qstr, cookie)`. O 3.18 só tem `fsnotify_ops.handle_event` com `(group, inode, inode_mark, vfsmount_mark, mask, data, data_type, file_name, cookie)`. Adicionar um adaptador que construa `qstr` a partir de `file_name` e encaminhe para o handler SUSFS legado. O port 4.9/2.3.0 tem um exemplo dessa ponte; usar apenas como referência de API, não como fonte da versão.
- O `fsnotify_alloc_group(&fsnotify_ops)` sem flags já é o caminho usado pelo 3.18 e pelo ramo legado do SUSFS; manter essa assinatura.
- O staging script adapta também `fsnotify_init_mark(mark, NULL)` e `fsnotify_add_mark(mark, group, inode, NULL, 0)`, que são as assinaturas do 3.18, e adiciona `susfs_is_current_proc_no_su()` com `TIF_PROC_NO_SU=34` para satisfazer o BakaSU UAPI 6.
## Bug de bitmask encontrado na fonte 2.2.0

Em `susfs.h`, a definição de `KSTAT_SPOOF_CTIME_TV_SEC` aparece como:

```c
#define KSTAT_SPOOF_CTIME_TV_SEC (1 < 8)
```

Isso avalia para `1`, colidindo com o bit `KSTAT_SPOOF_INO`. A porta precisa corrigir para `(1 << 8)` no kernel e na definição equivalente do userspace/CLI. A correção ainda não foi aplicada: não alterar apenas o header do kernel antes de localizar a definição do CLI, para não criar divergência de protocolo.

## Referência de porting antigo

O repositório `wxx9248/susfs4ksu` contém uma porta SUSFS 2.3.0 para Linux 4.9. Ela é útil apenas como referência de adaptação VFS antiga (por exemplo `mmap_sem`, `vfs_kern_mount`, `ida_get_new_above`, `generic_readlink` e `kstat` sem `result_mask`). Não copiar sua versão 2.3.0 para esta branch: a fonte de produção continua fixada em SUSFS 2.2.0.

## Plano de integração

1. Copiar os três arquivos core da subárvore SUSFS fixada para `fs/susfs.c` e `include/linux/susfs*.h` durante o build.
2. Aplicar patch local Linux 3.18 para static keys, bits, nameidata, filename_lookup e VFS/proc/mm hooks.
3. O staging script já adiciona `fs/susfs.o` e o overlay BakaSU separa `KSU_SUSFS` como feature independente, mantendo Manual Hook; a chamada `susfs_init()` fica no caminho Manual Hook.
4. Manter a ABI BakaSU UAPI 6 e não expor Inline Hook como método para este kernel 3.18.
5. Habilitar exatamente os recursos presentes no IKCONFIG antigo e compilar.
6. Testar cada recurso isoladamente e em conjunto; depois validar boot e runtime no Motorola One Deen.

## Estado

- [x] SUSFS v2.2.0 fixado como submódulo Git.
- [x] Workflow valida SHA e existência dos três arquivos core.
- [x] `scripts/prepare-susfs-318.py` criado e ligado ao workflow para copiar o core, adicionar o objeto condicional e aplicar shims de static key/fsnotify/no-su.
- [x] `nameidata.state`, inicialização em `path_init()` e exportação de `filename_lookup()` adicionados.
- [x] Call sites SUS_PATH em `fs/namei.c` e open redirect em `do_filp_open()`/`generic_readlink()` adicionados sob guards de configuração.
- [ ] Execução do workflow confirma staging e compilação do objeto/call sites.
- [ ] Restantes call sites Linux 3.18 de readdir, mount, kstat/statfs, procfs, cmdline, kallsyms e mm concluídos.
- [ ] Kconfig coexistindo com BakaSU Manual Hook.
- [ ] Build ARM64 concluído.
- [ ] Recursos funcionais validados no dispositivo.

Este documento é auditoria de compatibilidade, não declaração de integração funcional.
