# BakaSU 35253/6 — requisito UAPI e estratégia de hooks no Linux 3.18.140

## Artefatos de referência

- APK inspecionado: `BakaSU_v4.2.0-rc3_35253-arm64-v8a-release.apk`
- SHA-256: `11a276b3ceb7e3102be14d5274fc472ed4ff9192777db924c57009363628c85a`
- Biblioteca nativa ARM64: `lib/arm64-v8a/libkernelsu.so`
- O APK expõe consultas JNI para versão do kernel, UAPI do kernel, UAPI do manager, versão completa e tipo de hook.
- A biblioteca procura o descritor `[ksu_driver]` em `/proc/self/fd` e consulta o driver por ioctl. A compatibilidade deve ser medida pela interface real, não apenas pelo texto da versão.

## Requisito UAPI confirmado no APK

A implementação nativa do APK retorna `6` como `KERNEL_SU_UAPI_VERSION` do manager. No código fonte do manager, `isFullFeatured()` avalia:

```kotlin
isManager && kernelUAPIVersion == managerUAPIVersion
```

Para o manager anexado ser reconhecido como **full featured**, o driver precisa responder UAPI 6 no campo `uapi_version` de `KSU_IOCTL_GET_INFO`. Alterar `KSU_VERSION_FULL`, o nome da release ou o número exibido não implementa os ioctls ausentes.

### Comparação entre revisões BakaSU

- A revisão `7c383cfeef3a2ac450f2f1273dae74bd50356d31`, associada ao sufixo `7c383cfe` visto no driver antigo, declara `KERNEL_SU_UAPI_VERSION = 5`.
- A revisão `5785bdb8091304322f597f67d50e0b79f9815cb2` declara UAPI 6 e acrescenta `KSU_IOCTL_LOOKUP_SYMBOLS` e `KSU_GET_INFO_FLAG_PREINIT` em relação à UAPI 5.
- A fórmula de versão do manager na revisão atual é `30000 + git rev-list --count HEAD + 700`. O código 35253 corresponde a uma contagem de 4553 commits nessa fórmula. A contagem deve ser confirmada no commit exato usado para gerar o APK; não presumir que qualquer ponta de `main` gere o mesmo versionCode.

A antiga revisão UAPI 5 pode oferecer compatibilidade parcial por caminhos legados, mas **não atende à condição de full featured do APK UAPI 6**. O teste objetivo é consultar ambos os valores e confirmar que kernel e manager reportam 6.

## Hooks e SUSFS: conflito da configuração upstream

No Kconfig BakaSU inspecionado, `KSU_MANUAL_HOOK` e `KSU_SUSFS` aparecem na mesma `choice` de método de hook. A seleção é exclusiva no Kconfig padrão.

Além disso, o `kernel/core/init.c` dessa revisão usa uma cadeia `#if / #elif`: quando `CONFIG_KSU_MANUAL_HOOK` está definido, essa ramificação inicializa Manual Hook; a ramificação `#elif CONFIG_KSU_SUSFS` não é executada. Portanto, forçar os dois símbolos no `defconfig` não reproduz automaticamente o kernel antigo.

O ZIP Mimir antigo é uma evidência de configuração/customização diferente: seu IKCONFIG recuperado contém simultaneamente `CONFIG_KSU_MANUAL_HOOK=y` e `CONFIG_KSU_SUSFS=y`, e a imagem contém nomes de rotinas SUSFS, inclusive open redirect e sus map. Isso não recupera as modificações locais que permitiam coexistência, nem demonstra isoladamente que `susfs_init()` foi executado.

### Estratégia de reconstrução

1. Fixar uma revisão BakaSU que implemente UAPI 6 e seja compatível com o APK 35253/6.
2. Manter **Manual Hook** como método de hook do kernel 3.18. Não usar Tracepoint Syscall Redirect, que é destinado a GKI2 5.10+.
3. Separar a inicialização SUSFS do seletor de método de hook: a adaptação local deve permitir Manual Hook e inicialização SUSFS no mesmo build, sem deixar a cadeia `#elif` suprimir `susfs_init()`.
4. Reconstituir a compatibilidade dos hooks SUSFS 2.2.0 contra as interfaces do fork 3.18.140. Não habilitar `CONFIG_KSU_SUSFS_*` sem os fontes correspondentes.
5. Confirmar que os hooks exigidos pelo Manual Hook estão inseridos nos pontos corretos de syscall/LSM/input desta árvore.
6. Validar a inicialização e a comunicação manager/daemon por ioctl antes de empacotar ZIP.

## Testes de aceitação BakaSU

- [ ] `KSU_IOCTL_GET_INFO` responde e o descritor `[ksu_driver]` é encontrado.
- [ ] `kernelUAPIVersion == 6` e `managerUAPIVersion == 6`.
- [ ] `isFullFeatured() == true`.
- [ ] `getFullVersion()` e `getHookType()` reportam a build real, sem falsificar versão para mascarar ABI.
- [ ] Testar root grant, allowlist/app profiles e eventos do daemon compatíveis com UAPI 6.
- [ ] Confirmar Manual Hooks em runtime e validar as rotinas SUSFS por testes próprios.
- [ ] Testar no Motorola One Deen ARM64 com logs/dmesg e manter imagem de recuperação disponível.

## Estado atual

- A branch do kernel ainda não contém a integração do driver BakaSU nem a porta SUSFS reconstruída.
- O APK 35253/6 exige UAPI 6 para o estado full featured; a revisão antiga identificada no binário reporta UAPI 5.
- O conflito entre o seletor upstream de hook e as duas opções presentes no IKCONFIG antigo exige uma adaptação explícita de fonte.
- Não há alegação de build ARM64, boot, comunicação UAPI, SUSFS operacional ou ZIP final neste estágio.

Este documento registra requisitos verificáveis e decisões de arquitetura. Não constitui uma integração funcional.
