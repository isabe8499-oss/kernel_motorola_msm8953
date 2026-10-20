# Deen Android 12 kernel integration notes

Target: Motorola One Deen, ARM64, Linux 3.18.140.

## BakaSU test phase

The isolated workflow `.github/workflows/deen-bakasu-test.yml` sets up BakaSU from its upstream setup script, enables `CONFIG_KSU=y` and `CONFIG_KSU_MANUAL_HOOK=y`, and attempts a test build. A successful build proves compilation only; boot and runtime behavior still require device testing.

## SUSFS 2.2.0 compatibility gate

Do not enable SUSFS in this 3.18 target as if it were supported. BakaSU's upstream compatibility notes state that SUSFS backports are supported from Linux 4.3+, while the manual BakaSU hook itself supports 3.4+. Kernel 3.18 therefore needs a separate, explicitly maintained port of SUSFS internals and compatibility fixes; no claim of a complete SUSFS 2.2.0 integration should be made until that port compiles and is tested. The build workflow intentionally leaves SUSFS disabled.

Upstream references:
- https://github.com/Baka-SU/BakaSU
- https://bakasu.org/guide/build
