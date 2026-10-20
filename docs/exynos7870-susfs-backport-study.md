# Exynos7870-Revived-Beta: estudo de backport para Deen

## Objetivo
Investigar o kernel Exynos7870 Revived como referência para portar, com adaptação e testes, SUSFS e melhorias de compatibilidade para o Motorola One Deen (Linux 3.18.140, Android 12).

## Referência upstream
- Repositório: https://github.com/Exynos7870-Revived-Beta/android_kernel_samsung_exynos7870
- Branch: `lineage-19.1-bpf-ksu`
- Base Linux: 3.18.140
- SUSFS presente: v1.5.5 (`include/linux/susfs.h`)
- Gerenciador/driver root: KernelSU-Next legacy, não BakaSU.
- SUSFS 2.2.0 não está provado nesta referência.

## Commits-chave analisados
1. `3a02547bc9325c67a80d84bbf1374d97761e3e68` — implementação central de SUSFS v1.5.5 no VFS.
2. `2b951cc3527804947fcaafd4eadf7d8c18dc7a6a` — integração SUSFS no KernelSU-Next.
3. `0ebedbb103e758b3f9a7152e3037aaba26d10dfe` — KernelSU-Next legacy e hooks manuais para Linux 3.18.
4. `a539cfa08d2e023c458b33d8cab9c8c689296e36` — habilita KSU/manual hooks/SUSFS nas defconfigs do Exynos.
5. `e54a2a457a3b44ebeb633cdfebd93917a1f67b35` — atualiza KernelSU-Next para v3.4.0-legacy e lista backports de compatibilidade para 3.18.

## Componentes SUSFS evidenciados na série de patches
- `fs/susfs.c`, `include/linux/susfs.h`, `include/linux/susfs_def.h`
- Hooks em `fs/dcache.c`, `fs/namei.c`, `fs/namespace.c`, `fs/proc_namespace.c`, `fs/proc/cmdline.c`, `fs/proc/fd.c`, `fs/proc/task_mmu.c`, `fs/readdir.c`, `fs/stat.c`, `fs/statfs.c`
- Integração de `CONFIG_KSU_SUSFS` e opções subordinadas no Kconfig/defconfigs
- Dados adicionais em `task_struct` e estruturas de mount
- Interface de comando por `prctl`/reboot supercall, conforme a série de patches

## Plano recomendado para Deen
1. Manter o branch de teste BakaSU isolado e obter build verde com hooks manuais completos antes de misturar SUSFS.
2. Criar branch independente de experimento SUSFS 1.5.5 a partir de uma base Deen compilável; não sobrescrever a branch principal.
3. Fazer port incremental dos patches por subsistema, não copiar o kernel Exynos inteiro: suas mudanças de Exynos, device tree, câmera, power/thermal e drivers específicos não são portáveis para MSM8953.
4. Primeiro portar os headers/Kconfig/core SUSFS; depois VFS/dcache/namei/stat/readdir; depois namespace/mount/proc; por fim integração SUSFS com o driver de root.
5. O ponto de integração SUSFS com KernelSU-Next não pode ser assumido compatível com BakaSU: mapear API/supercalls, ciclos de boot, SELinux e hooks equivalentes.
6. Rodar builds após cada grupo de patches, checar config final, símbolos e warnings/errors. Só então empacotar imagem.
7. Teste de boot/runtime no dispositivo é uma etapa separada; uma compilação verde não confirma funcionalidade SUSFS nem segurança de ocultação.

## Alertas
- Não ativar `CONFIG_KSU_SUSFS=y` sozinho sem portar o código do kernel e a interface de userspace correspondente.
- SUSFS 2.2.0 exigiria revisão de diferenças de API e dependências; a referência comprovada é SUSFS 1.5.5.
- Não cherry-pickear o kernel Exynos completo: o hardware é Samsung Exynos 7870, enquanto Deen é Qualcomm MSM8953.
- Qualquer imagem de boot experimental precisa de recuperação/backup e validação por fastboot/recovery antes de flash.

## Referências
- https://github.com/Exynos7870-Revived-Beta/android_kernel_samsung_exynos7870/tree/lineage-19.1-bpf-ksu
- https://github.com/Exynos7870-Revived-Beta/android_kernel_samsung_exynos7870/commit/3a02547bc9325c67a80d84bbf1374d97761e3e68
- https://github.com/Exynos7870-Revived-Beta/android_kernel_samsung_exynos7870/commit/2b951cc3527804947fcaafd4eadf7d8c18dc7a6a
- https://github.com/Exynos7870-Revived-Beta/android_kernel_samsung_exynos7870/commit/0ebedbb103e758b3f9a7152e3037aaba26d10dfe
