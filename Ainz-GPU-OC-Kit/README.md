# Ainz GPU OC Kit

**Real GPU overclock for the Redmi A5 / POCO C71 (`serenity`, Unisoc UMS9230E / T7250).**

Author: **Ainz** · License: MIT · Version: 1.0.0

Most "GPU overclock" guides for Unisoc devices only edit the OPP table. On
`serenity` that changes the labels the driver reports, not the clock: the GPU
keeps running at **850 MHz**. This kit changes the real clock source — it
reprograms **GPLL** through `assigned-clocks` / `assigned-clock-rates` on the
GPU device-tree node — and verifies every byte of the resulting
`vendor_boot.img`.

The kit builds images only. **It never flashes anything.** You flash the output
yourself and keep a stock image for rollback.

---

## Results on real hardware

Measured on a Redmi A5 (`serenity`), Android 17 vendor_boot, Mali-G57 MP1:

| GPU clock | How | Boot | Stability |
|---|---|---|---|
| 850 MHz | stock | OK | baseline |
| 1.0 GHz label | OPP-only edit | OK | fake — still 850 MHz |
| **1.1 GHz** | **GPLL forced (this kit)** | **OK** | **stable, 0 GPU faults, +29%** |
| 1.15 GHz | GPLL forced | OK | screen artifacts under load |
| 1.2 GHz | GPLL forced | OK | screen artifacts under load |
| 1.6 GHz | GPLL forced | hangs | `GPU fault 0x4002` |

The practical ceiling on this device is **1.1 GHz**, because the GPU rail is
clamped by the hardware DVFS engine (see below). GPLL itself can reach
1.6 GHz, but the GPU cannot run that fast at the rail the hardware provides.

### The voltage caveat

The `voltage` field in `operating-points` / `sprd,dvfs-lists` is
**informational only** on this platform. The DCDC_GPU rail is driven by the
on-chip **topdvfs** engine, not by the DT OPP values:

| GPU DVFS level | Measured `vddgpu` |
|---|---|
| 384–614.4 MHz | ~750 mV |
| 768 MHz | ~781 mV |
| 1.1 GHz (GPLL) | ~912 mV |

Even a direct debugfs write to `DCDC_GPU/voltage` is reverted immediately.
Consequences:

- Raising the OPP voltage to 1200 mV does **not** raise the rail and does not
  make 1.6 GHz stable.
- `--mali-supply` connects `DCDC_GPU` to the Mali kbase regulator path. kbase
  does call `regulator_set_voltage()`, but topdvfs still wins. Treat this
  variant as an experiment, not as a voltage unlock.
- A real 1.2 V rail would require disabling or reprogramming topdvfs
  (`0x150` tune-enable bits). This kit does not do that.

Full details: [`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md) and
[`docs/TECHNICAL.md`](docs/TECHNICAL.md).

---

## Requirements

- Redmi A5 / POCO C71 (`serenity`, UMS9230E / T7250) — **only this device**.
- A **stock** `vendor_boot.img` from your current firmware (100 MiB / 104,857,600
  bytes, FDT at `0x2482040`).
- Python 3.8+. No third-party packages.
- A working rollback path: stock `vendor_boot.img` and a way to flash it.

The kit does not bundle stock or prebuilt images. Extract `vendor_boot.img`
from your firmware package, or dump it from your device before modifying
anything.

---

## Quick start

```bash
# 1. Inspect the stock image (no changes)
python3 oc.py verify vendor_boot.img

# 2. Build the proven-stable 1.1 GHz image
python3 oc.py build --stock vendor_boot.img --freq-mhz 1100 --volt-mv 1000

# 3. Verify the output against the stock image
python3 oc.py verify vendor_boot_oc_1100mhz_1000mv.img --stock vendor_boot.img
```

`build` prints the SHA-256 and a `verify: PASS` line. The stable build is
byte-for-byte reproducible:

```
cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277
```

Flash it yourself:

```bash
adb reboot fastboot
fastboot flash vendor_boot vendor_boot_oc_1100mhz_1000mv.img
fastboot reboot
```

Rollback:

```bash
fastboot flash vendor_boot vendor_boot.img
```

> The FDT offset, wrapper fields and boot-header `dtb_size` are patched
> together. Flashing a half-patched image can prevent the device from booting.
> Always run `verify` before flashing.

---

## CLI reference

```
python3 oc.py --version
python3 oc.py build --stock vendor_boot.img --freq-mhz 1100 --volt-mv 1000
python3 oc.py verify vendor_boot_oc_1100mhz_1000mv.img --stock vendor_boot.img
```

### `build`

| Option | Meaning |
|---|---|
| `--stock PATH` | Stock `vendor_boot.img` (default `vendor_boot.img`). Must have the stock 850 MHz top OPP. |
| `--out PATH` | Output path. Default: `vendor_boot_oc_<freq>mhz_<volt>mv[_mali].img`. |
| `--freq-mhz N` | Top OPP frequency in MHz. Also the GPLL rate unless `--gpll-mhz` is given. |
| `--gpll-mhz N` | GPLL rate in MHz (default: same as `--freq-mhz`). |
| `--volt-mv N` | Top OPP voltage in mV (default 800). Informational on this device. |
| `--mali-supply` | Add `mali-supply = <&DCDC_GPU>` (experimental). |
| `--i-know-the-risks` | Required for >1200 MHz or >1000 mV. |

The builder refuses any input that is not a clean stock image: the top OPP must
be 850 MHz @ 800 mV, the top DVFS cell must be the GPLL cell `0x08`, and the
image must not already contain `assigned-clock-rates` or `mali-supply`.

### `verify`

Prints the GPU node (phandles, OPP table, DVFS levels, GPLL rate) and checks:

- image size is 104,857,600 bytes;
- FDT magic at `0x2482040`;
- boot header `0x834` = 64 + FDT size;
- wrapper `+0x04` = 64 + FDT size;
- wrapper `+0x20` = FDT size;
- with `--stock`: same file length, bytes outside the FDT unchanged, and the
  bytes after the FDT unchanged.

Exit code is `0` on PASS, `1` on FAIL.

---

## How it works (short version)

The GPU has five DVFS levels. Levels 0–3 are fixed PLLs (384 / 512 / 614.4 /
768 MHz). Level 4 is **GPLL**, and on stock firmware nothing ever calls
`clk_set_rate()` on it, so it stays at 850 MHz. Editing the OPP table only
re-labels level 4.

This kit adds to the GPU node:

```dts
assigned-clocks      = <&pll1 0x1d>;   /* GPLL (phandle 0x24, cell 0x1d) */
assigned-clock-rates = <1100000000>;    /* 1.1 GHz */
```

`of_clk_set_defaults()` applies this before the GPU driver probes, so GPLL is
reprogrammed once and stays there. The OPP table is updated to match the new
top entry so `devfreq` exposes the frequency, but the real clock is GPLL.

GPLL is consumed only by the GPU on this SoC, so this does not affect other
blocks. If the PLL reprogramming fails, the GPU falls back to 850 MHz; it does
not brick the device.

More: [`docs/TECHNICAL.md`](docs/TECHNICAL.md).

---

## Safety

- Only values **≤ 1.1 GHz** have been validated on hardware.
- The safety gate blocks >1200 MHz or >1000 mV unless `--i-know-the-risks`
  is passed. This is a speed bump, not a guarantee.
- 1.15/1.2 GHz produce visible artifacts under load; 1.6 GHz hangs the GPU at
  boot.
- The `--mali-supply` variant boots at 1.1 GHz but does **not** raise the rail.
  Do not use it to justify higher clocks.
- Overclocking can hang the boot, corrupt data or damage hardware. Keep a
  stock image and know how to enter fastboot.

Read [`docs/SAFETY.md`](docs/SAFETY.md) before flashing.

---

## Repository layout

```
Ainz-GPU-OC-Kit/
├── oc.py                 # build/verify CLI
├── README.md             # this file
├── README.vi.md          # Vietnamese README
├── CHANGELOG.md
├── AUTHORS
├── LICENSE
└── docs/
    ├── TECHNICAL.md      # FDT layout, GPLL, why OPP-only is fake
    ├── MEASUREMENTS.md   # on-device evidence
    └── SAFETY.md         # risks, limits, rollback
```

## Credits

- **Ainz** — author and maintainer: investigation, tooling, device testing.
- The Unisoc GPU DVFS behaviour was confirmed by disassembling the shipped
  `gpu_pm_ums9230.ko` and `mali_kbase_ums9230.ko` modules and by reading the
  live GPLL registers on the device.

## License

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 Ainz.

This project is not affiliated with Xiaomi, Redmi, POCO or Unisoc. Flashing
modified images voids warranties and is done at your own risk.
