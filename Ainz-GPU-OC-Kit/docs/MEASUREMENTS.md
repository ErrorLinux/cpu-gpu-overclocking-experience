# Measurements

All numbers below were taken on a real Redmi A5 (`serenity`, UMS9230E / T7250,
Mali-G57 MP1), Android 17, kernel `6.18.21-android17`. Commands were run over
`adb` with root (`su`). Nothing in this document was obtained by simulation.

---

## 1. Test device

| Item | Value |
|---|---|
| Model | Redmi A5 / POCO C71 (`serenity`) |
| SoC | Unisoc UMS9230E (T7250) |
| GPU | Mali-G57 MP1 at `23100000.gpu` |
| GPU node | `/soc/mm/gpu@23100000` |
| Kernel | `6.18.21-android17-5-gf8ee977e062b-ab16100350-4k` |
| Vendor boot | 100 MiB, FDT at `0x2482040` |

---

## 2. Stock behaviour

### 2.1 Reported frequencies

```
$ cat /sys/class/devfreq/23100000.gpu/available_frequencies
850000000 768000000 614400000 512000000 384000000
```

The top level reports 850 MHz. This matches GPLL, which stock firmware never
reprograms.

### 2.2 GPLL registers

Syscon `0x645a0000`, GPLL registers at `0x48 / 0x4c / 0x50`:

```
0048: 000007ab
004c: 10589d8a
0050: 00000005
```

Decoded:

```
nint = (0x10589d8a >> 23) & 0x7f = 32
kint =  0x10589d8a        & 0x7fffff = 5,807,498
f    = 26e6 * (32 + 5807498 / 2^23) = 850.00 MHz
```

### 2.3 What the driver does

`gpu_pm_ums9230.ko` (`platform_set_freq_volt`) writes only the DVFS cell index
(`0x04`–`0x08`) through `regmap_update_bits`. It does not call `clk_set_rate`
for any GPU PLL. A `clk_set_rate` tracepoint recorded **0 calls** during boot
and GPU load. Editing the OPP table therefore changes labels, not the clock.

---

## 3. Real overclock: 1.1 GHz

Build used: `vendor_boot_oc_1100mhz_1000mv.img`
(SHA-256 `cf0735a6…a5277`), GPLL 1.1 GHz, top OPP 1100 MHz @ 1000 mV.

### 3.1 GPLL after boot

```
0048: 000007af
004c: 15276276
0050: 00000005
```

Decoded:

```
nint = 42
kint = 2,581,110
f    = 26e6 * (42 + 2581110 / 2^23) = 1100.00 MHz
```

This matches `assigned-clock-rates = <1100000000>` exactly.

### 3.2 Runtime state

```
$ cat /sys/class/devfreq/23100000.gpu/available_frequencies
1100000000 768000000 614400000 512000000 384000000

$ cat /sys/class/devfreq/23100000.gpu/cur_freq
1100000000

$ cat /sys/kernel/debug/mali0/gpu_freq_time
1100000000: busy ...
```

The level-4 bucket accumulates busy time, so the GPU actually executes at
1.1 GHz. `dmesg` showed **0 GPU faults** and **0 soft resets** during boot and
normal use; the launcher and games ran normally.

### 3.3 Stability sweep

| GPLL | Boot | Result |
|---|---|---|
| 850 MHz | OK | stock baseline |
| 1.0 GHz (OPP-only) | OK | still 850 MHz real |
| **1.1 GHz** | **OK** | **0 faults, stable** |
| 1.15 GHz | OK | screen artifacts under load |
| 1.2 GHz | OK | screen artifacts under load |
| 1.5 GHz (OPP-only) | OK | fake 1.5 GHz label, 850 MHz real |
| 1.6 GHz | hangs | `t6xx: GPU fault 0x4002`, repeated soft reset, boot never completes |
| 2.2 GHz | not tested | above GPLL maximum (1.6 GHz) |

---

## 4. GPU rail (`vddgpu`) measurements

The rail is exposed by the SPRD regulator debugfs:

```
$ cat /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage
912
```

The value is in mV. `regulator.2` (`vddgpu`) reports microvolts:

```
$ cat /sys/class/regulator/regulator.2/name
vddgpu
$ cat /sys/class/regulator/regulator.2/microvolts
912500
```

### 4.1 Rail vs DVFS level

Using the `userspace` devfreq governor to pin each level:

| Level | Frequency | Rail |
|---|---|---|
| 0 | 384 MHz | 750 mV |
| 1 | 512 MHz | 750 mV |
| 2 | 614.4 MHz | 750 mV |
| 3 | 768 MHz | 781 mV |
| 4 | 1.1 GHz (GPLL) | 912 mV |

These values do **not** match the DT OPP voltages (700 / 750 / 750 / 800 /
800 mV stock, or 1200 mV in the patched builds). The rail is chosen by the
topdvfs hardware engine per DVFS cell.

A reading taken immediately after a frequency switch can briefly show the
previous level because of the regulator ramp delay
(`regulator-ramp-delay = <0x61a8>`, 25 ms). Readings above were taken after the
rail settled.

### 4.2 Direct PMIC write is overridden

The SPRD regulator driver exposes `voltage` and `locken`. To write, `locken`
must be opened first:

```
$ echo 0x6e7f > /sys/kernel/debug/sprd_regulator/locken
$ echo 1200 > /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage
$ cat /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage
912
$ cat /sys/class/regulator/regulator.2/microvolts
912500
```

The write is accepted (no error) but the value is immediately reverted. The
topdvfs engine owns the rail.

Descriptor for `DCDC_GPU` (`sc2730_regulator.ko`, shipped in the vendor_boot
ramdisk): `vsel_reg = 0x1854`, `vsel_mask = 0x1ff`, step 3125 µV, 512
selectors. 1200 mV maps to selector 384 (`0x180`). The register write itself is
valid; the override happens at the hardware DVFS level.

### 4.3 `mali-supply` variant

Build: `vendor_boot_oc_1100mhz_1200mv_mali.img`
(SHA-256 `02a90f88…fec6`). This booted successfully.

Evidence that kbase used the new supply:

```
$ ls /sys/class/regulator/regulator.2/
23100000.gpu-mali  consumer:platform:23100000.gpu  num_users  ...

$ cat /sys/class/regulator/regulator.2/num_users
1

$ cat /sys/class/regulator/regulator.2/microvolts
912500
```

`mali_kbase_ums9230.ko` does call `regulator_set_voltage()` from
`kbase_devfreq_target()` (confirmed by disassembly and relocations), and the
consumer link proves the `mali-supply` lookup succeeded. The rail still reads
912.5 mV, so topdvfs overrides the request.

Conclusion: `mali-supply` is a working diagnostic path, not a voltage unlock.

---

## 5. Reproducing the measurements

```bash
# debugfs is normally mounted by init; mount it if needed
adb shell su -c 'mount -t debugfs none /sys/kernel/debug'

# reported GPU state
adb shell su -c 'cat /sys/class/devfreq/23100000.gpu/available_frequencies'
adb shell su -c 'cat /sys/class/devfreq/23100000.gpu/cur_freq'

# rail
adb shell su -c 'cat /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage'
adb shell su -c 'cat /sys/class/regulator/regulator.2/microvolts'

# live GPLL registers (syscon debugfs)
adb shell su -c 'cat /sys/kernel/debug/regmap/dummy-syscon@0x00000000645a0000/registers' | sed -n '5,6p'
```

To sweep levels (restore `performance` afterwards):

```bash
adb shell su -c 'echo userspace > /sys/class/devfreq/23100000.gpu/governor'
adb shell su -c 'echo 384000000 > /sys/class/devfreq/23100000.gpu/min_freq'
adb shell su -c 'echo 384000000 > /sys/class/devfreq/23100000.gpu/userspace/set_freq'
adb shell su -c 'cat /sys/class/devfreq/23100000.gpu/cur_freq'
adb shell su -c 'cat /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage'
```

Restore:

```bash
adb shell su -c 'echo 1100000000 > /sys/class/devfreq/23100000.gpu/min_freq'
adb shell su -c 'echo 1100000000 > /sys/class/devfreq/23100000.gpu/max_freq'
adb shell su -c 'echo performance > /sys/class/devfreq/23100000.gpu/governor'
adb shell su -c 'echo 0xffff > /sys/kernel/debug/sprd_regulator/locken'
```

---

## 6. Image hashes

| Image | SHA-256 |
|---|---|
| `vendor_boot.img` (stock 850 MHz) | `091521617e189e94a1d423a77010b4bc207949e96625b980ac6b58f3e01640ee` |
| `vendor_boot_oc_1100mhz_1000mv.img` | `cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277` |
| `vendor_boot_oc_1100mhz_1200mv.img` | `76ba8995f01702a50c818b6040b52921032df752b57e31269dd9dcd4e03b8295` |
| `vendor_boot_oc_1100mhz_1200mv_mali.img` | `02a90f8823221e5b72aa3aff269ac84da8bfca18db2a5ad658c2126e93edfec6` |
| `vendor_boot_oc_1600mhz_1200mv_mali.img` | `fe21059f4f436f2a3b54aeae405b5f76d6f42da99ec33cc90e2a339102b0bd73` |

The 1.1 GHz / 1000 mV image is the validated build. The 1200 mV images were
built to prove that the OPP voltage field is cosmetic; they are not recommended
for daily use.
