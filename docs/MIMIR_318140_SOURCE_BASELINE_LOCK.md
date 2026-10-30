# Mimir Linux 3.18.140 — baseline de fontes fixadas

Este arquivo fixa as revisões usadas na reconstrução. Os números de versão são verificados nos próprios fontes; não usar branches móveis em compilação final.

## Repositório alvo

- Kernel: https://github.com/isabe8499-oss/kernel_motorola_msm8953
- Branch de integração: `integration/bakasu-35253-susfs22-nomount`
- Alvo: Motorola One Deen / MSM8953 / ARM64 / Linux 3.18.140.

## Dependências fixadas

| Componente | Revisão | Verificação |
|---|---|---|
| BakaSU | `5785bdb8091304322f597f67d50e0b79f9815cb2` | HEAD de `main`; UAPI 6; contagem de 4553 commits = manager versionCode 35253 |
| SUSFS | `4003ecf2d01c6d13fa8edf6c4f2607365738dc3d` | `kernel_patches/include/linux/susfs.h` declara `SUSFS_VERSION "v2.2.0"` |
| NoMount | `bf1847f98fed382369c43bfd652cd93774b9b8e3` | tag/release v2.2.0; protocolo 22 |

### Evidências dos artefatos antigos

- ZIP antigo: `Kernel-MTONEDEEN-bakaSU+SUSFS-kernel 3.18.zip`
- SHA-256: `ff8fce5eed51335748f313a709dac89673e001abeb30f2a4b7d24d6509e8b282`
- APK BakaSU 35253/6: `BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk`
- SHA-256: `11a276b3ceb7e3102be14d5274fc472ed4ff9192777db924c57009363628c85a`

O IKCONFIG extraído do ZIP antigo tem `CONFIG_KSU_MANUAL_HOOK=y` e as opções `CONFIG_KSU_SUSFS_*` ligadas. A imagem também contém nomes de rotinas SUSFS, incluindo open redirect e sus map. Isso é evidência binária para reconstrução, não os fontes nem os patches locais que produziram a imagem.

## Restrições de integração que permanecem

1. A configuração padrão BakaSU coloca Manual Hook e SUSFS Inline Hook na mesma Kconfig choice. O build antigo usava ambos os símbolos, portanto a integração local precisa separar a inicialização SUSFS do seletor de hooking e preservar Manual Hook no kernel 3.18.
2. SUSFS 2.2.0 foi fixado na revisão declarada acima; não copiar patches de 5.10 cegamente para 3.18. Cada ponto de chamada VFS/proc/mm/SELinux precisa de backport específico.
3. NoMount v2.2.0 usa interfaces modernas que precisam do adaptador descrito em `NOMOUNT_V22_LINUX_318140_COMPATIBILITY.md`.
4. O workflow existente ainda usa script externo móvel; o build reproduzível deve clonar essas dependências nos SHAs acima e verificar os SHAs antes do Kconfig/build.
5. Nenhuma dessas três dependências está integrada/compilada nesta etapa. Esta tabela é um lockfile documental de fontes, não uma afirmação de compilação bem-sucedida.

## Gates de reprodução

- [ ] Checkout exato dos três SHAs e verificação de cada SHA no log do CI.
- [ ] Defconfig contém apenas opções com implementação conectada.
- [ ] Manual Hook e SUSFS inicializam juntos sem a ramificação `#elif` omitir `susfs_init()`.
- [ ] BakaSU responde UAPI 6; manager e kernel reportam 6.
- [ ] SUSFS identifica v2.2.0 e todos os recursos habilitados passam teste funcional.
- [ ] NoMount responde protocolo 22 e passa teste funcional/concurrency.
- [ ] Build ARM64 reproduzível, imagem de boot inspecionada e ZIP AnyKernel3 verificado.
