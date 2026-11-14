# Motorola One Deen — Linux 5.15 Port Audit

Date: 2026-11-14

## Scope

This is an audit-only branch. It does not change the existing kernel sources, defconfig, device trees, or build workflow. The current working objective is AOSPA Uvite (Android 14) on Motorola One Deen (deen / XT1941-3), with a device-specific Linux 5.15 kernel and no SUSFS/NoMount integration.

## Audited source baseline

- Repository: https://github.com/isabe8499-oss/kernel_motorola_msm8953
- Source branch: `lineage-18.1`
- Audited branch head: `1f700e4c2e31c435358e7531dfc0c2e41e2a2684`
- Kernel Makefile: Linux 3.18.140
- Device defconfig: `arch/arm64/configs/deen_defconfig`
- Deen-specific supplemental config: `arch/arm64/configs/ext_config/mot8953-deen.config`

## Reusable Deen-specific material found

The existing tree contains a substantial vendor device implementation. Preserve and study these sources before writing replacements:

- `arch/arm/boot/dts/qcom/msm8953-deen.dtsi`
- `arch/arm/boot/dts/qcom/msm8953-deen-pvt1.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-pvt2.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-dvt1a.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-dvt1b.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-dvt2.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-evt1.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-evt2.dts`
- `arch/arm/boot/dts/qcom/msm8953-deen-pinctrl.dtsi`
- `arch/arm/boot/dts/qcom/msm8953-camera-sensor-mot-deen.dtsi`
- `arch/arm/boot/dts/qcom/msm8953-moto-common.dtsi`
- `arch/arm/boot/dts/qcom/msm8953-moto-pinctrl.dtsi`

The legacy DTS build Makefile selects seven Deen board revisions under `CONFIG_DEEN_DTB`. The Deen DTSI documents, among other items, the 720x1520 panel variants, Focaltech FT8006U and Novatek touchscreen nodes, GPIO/pinctrl assignments, camera power rails and Android fstab entries. These are high-value hardware references, not files to copy unchanged into a 5.15 tree.

The supplemental config enables:
- `CONFIG_ARCH_MSM8953`
- `CONFIG_DEEN_DTB`
- Focaltech MMI and NT36xxx touchscreen support
- MSM camera stack and Deen multi-camera configuration
- KGSL / Adreno and KGSL IOMMU
- Qualcomm MDSS and MDSS PLL
- MSM RPM SMD and related logging
- Deen-specific sensors and TFA9874 audio codec support

The final 5.15 config must be reconstructed against the target kernel's Kconfig symbols. Do not append this old config blindly.

## Existing build workflow findings

The current `.github/workflows/mimir-build.yml`:
- checks out the repository and invokes an external Mimir build script from `Vhmit/mimir-build-script`, branch `v3.x-gcc`;
- uses the legacy GCC 4.9 toolchain;
- sets `ARCH=arm64` and `CONFIG_FILE=deen_defconfig`;
- expects `Image.gz-dtb`;
- packages through the Deen AnyKernel3 branch;
- has optional KernelSU and DroidSpaces inputs;
- references Telegram secrets and external log/file upload services.

This workflow is specific to the existing 3.18 kernel and must not be reused unchanged for Linux 5.15. A new reproducible build workflow should pin the source revision and toolchain, use the build system appropriate to the selected kernel branch, upload GitHub Actions artifacts, and avoid requiring Telegram/Gofile secrets.

## External upstream research

1. Android Common Kernel officially maintains an `android14-5.15` branch. Android 14 supports this ACK family. See:
   - https://source.android.com/docs/core/architecture/kernel/android-common
   - https://source.android.com/docs/setup/reference/bazel-support
   - https://android.googlesource.com/kernel/common/

2. A Motorola One (deen, MSM8953) upstream arm64 device-tree patch was submitted in August 2026 and subsequently committed to an upstream development tree in September 2026:
   - https://lkml.iu.edu/hypermail/linux/kernel/2608.1/03370.html
   - https://git.zx2c4.com/wireguard-linux/commit/arch/arm64/boot/dts/qcom?id=b62af30ebdb4ae4ec6230c5e39eea97f65b9f5ea

   The initial upstream DTS enables a limited set of functions: I2C peripherals/NFC, keys, PM8953 regulators, remote processors and USB. It explicitly leaves display/panel-dependent functions disabled. This is a valuable modern DT reference, not proof of full Android hardware support.

3. The MSM8953 mainline development tree is:
   - https://github.com/msm8953-mainline/linux

## Architecture decision

Do not turn the old 3.18 tree into a 5.15 tree by changing version fields. Keep this repository and its existing branches intact as the vendor reference archive.

Recommended target source:
- Start from the Android Common Kernel `android14-5.15` branch for Android 14 integration and Android-specific kernel interfaces.
- Evaluate the MSM8953 mainline development tree and the upstream Motorola One DTS as references for modern SoC/device descriptions.
- Port or reimplement required Deen hardware support in dependency order. The old Qualcomm vendor drivers and Android userspace HALs may depend on private interfaces and cannot be assumed to work with upstream/ACK drivers.
- Keep vendor modules/KMI compatibility as an explicit risk: a GKI kernel is not a drop-in replacement for this device's legacy vendor stack.

## Work plan and gates

### Gate A — hardware and boot facts
Collect from the actual XT1941-3:
- `uname -a`, `/proc/cmdline`, relevant `getprop` values;
- boot/recovery/vendor partition layout and slot arrangement;
- boot image header/version, DTB/DTBO arrangement, page size and command line;
- exact active board revision and touchscreen/panel variant;
- current vendor firmware build and HAL inventory.

Do not publish IMEI, serial number, Wi-Fi/Bluetooth addresses, or other unique identifiers in logs.

### Gate B — source compatibility matrix
Map each legacy subsystem to its 5.15 target:
- clocks, resets, pinctrl, regulators, RPM/SMD, SMEM, remoteproc, SPMI;
- SDHCI/eMMC, USB/PHY, I2C/SPI;
- display/MDSS/DSI/panel;
- KGSL/Adreno 506 and IOMMU;
- audio/ADSP/codec;
- camera/ISP and sensors;
- Wi-Fi/Bluetooth and modem.

For each subsystem, record source provenance, target API differences, dependencies, firmware/HAL dependencies, and test evidence.

### Gate C — minimal bootable kernel
Build a 5.15 kernel and matching DTB/DTBO with serial/earlycon and initramfs/ADB recovery strategy. First prove boot and basic storage/USB; do not package a daily-driver image yet.

### Gate D — hardware enablement
Enable display/touch, then power/thermal, audio, connectivity, camera, sensors and telephony in controlled increments. Require logs and regression tests for every stage.

### Gate E — AOSPA integration
Only after the device kernel and vendor interface are understood, create the AOSPA Uvite device product and integrate the selected kernel artifacts.

## Immediate next actions

1. Obtain a read-only device snapshot from ADB and Fastboot; verify the user's report that the bootloader is unlocked.
2. Identify which Deen board DTS revision and panel/touchscreen combination match the physical phone.
3. Compare the legacy Deen DTS with the upstream 2026 Motorola One DTS.
4. Pin the exact ACK `android14-5.15` source revision and inspect its build instructions.
5. Produce a subsystem-by-subsystem port matrix before moving or rewriting any driver.

## Non-goals for this branch

- No changes to the existing 3.18 kernel implementation.
- No SUSFS or NoMount.
- No automatic flashing or destructive Fastboot commands.
- No claim of a bootable 5.15 image until an actual device test passes.
