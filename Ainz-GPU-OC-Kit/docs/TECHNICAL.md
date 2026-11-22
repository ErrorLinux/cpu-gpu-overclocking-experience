# Technical notes

Ainz GPU OC Kit — Redmi A5 / POCO C71 (`serenity`, Unisoc UMS9230E / T7250,
Mali-G57 MP1).

This document explains what the kit changes and why the common OPP-only
"overclock" does nothing on this device.

---

## 1. Image layout

`vendor_boot.img` is 100 MiB (104,857,600 bytes). The GPU device tree is stored
as a raw FDT inside the vendor ramdisk area, followed by a 64-byte SPRD wrapper:

| Region | Offset | Size / value |
|---|---|---|
| Boot header | `0x0` | `dtb_size` (little-endian u32) at `0x834` |
| SPRD wrapper | `0x2482000` | 64 bytes, magic `0xd7b7ab1e` |
| FDT | `0x2482040` (38,281,280) | 146,594 bytes stock |
| FDT padding | after FDT | 798 bytes available |
| Rest of image | — | ramdisk table / bootconfig |

Wrapper fields used by the bootloader:

| Field | Meaning |
|---|---|
| `+0x04` | container size = 64 + FDT size (big-endian) |
| `+0x20` | FDT size (big-endian) |

> Some older notes quote `0x2482080` for the FDT. The correct offset on this
> image is **`0x2482040`**; `0x2482080` is inside the FDT header. The kit uses
> `0x2482040` and rejects images where the magic is not there.

Stock FDT header: totalsize 146,594; struct block 130,664; strings block 15,874.
The patched FDT grows by 57 bytes (plain) or 85 bytes (with `mali-supply`),
which still fits in the 798-byte padding.

---

## 2. Why editing the OPP table is not an overclock

The GPU node `/soc/mm/gpu@23100000` has five DVFS levels:

```dts
operating-points = <
    0x5dc00 0xaae60   /* 384.0 MHz @ 700 mV */
    0x7d000 0xb71b0   /* 512.0 MHz @ 750 mV */
    0x96000 0xb71b0   /* 614.4 MHz @ 750 mV */
    0xbb800 0xc3500   /* 768.0 MHz @ 800 mV */
    0xcf850 0xc3500   /* 850.0 MHz @ 800 mV */
>;

sprd,dvfs-lists = <
    0x5dc00 0xaae60 0x04 0x01
    0x7d000 0xb71b0 0x05 0x01
    0x96000 0xb71b0 0x06 0x01
    0xbb800 0xc3500 0x07 0x01
    0xcf850 0xc3500 0x08 0x01
>;
```

The last two cells are the **hardware DVFS cell** and an enable flag. The cell
selects a clock source in the topdvfs block:

| Level | Cell | Clock source | Real frequency |
|---|---|---|---|
| 0 | `0x04` | `twpll-384m` | 384 MHz |
| 1 | `0x05` | `twpll-512m` | 512 MHz |
| 2 | `0x06` | `lpll-614m4` | 614.4 MHz |
| 3 | `0x07` | `twpll-768m` | 768 MHz |
| 4 | `0x08` | **GPLL** | GPLL rate (850 MHz stock) |

`gpu_pm_ums9230.ko` (`platform_set_freq_volt`) binary-searches the frequency,
writes the **cell index** through `regmap_update_bits`, and saves the index. It
never calls `clk_set_rate()` or `clk_set_parent()` for the PLLs. The Mali kbase
module also has no `clk_set_rate` symbol. A tracepoint on `clk_set_rate` records
zero calls during boot and GPU load.

Therefore changing the OPP frequency/voltage only changes the labels reported
by `devfreq`; level 4 still selects GPLL at 850 MHz.

### GPLL register evidence

GPLL lives behind the syscon at `0x645a0000` (debugfs:
`dummy-syscon@0x00000000645a0000/registers`), offsets `0x48 / 0x4c / 0x50`.

Decode (`f_pll` in `ums9230-clk.c`, refclk 26 MHz, `div_s = 1`, SDM enabled):

```
nint = (reg >> 23) & 0x7f
kint =  reg        & 0x7fffff
f    = 26e6 * (nint + kint / 2^23)
```

Measured:

| State | `nint` | `kint` | GPLL |
|---|---|---|---|
| stock | 32 | 5,807,498 | 850.00 MHz |
| patched 1.1 GHz | 42 | 2,581,110 | 1100.00 MHz |

Register `0x48` changed from `0x7ab` to `0x7af` (PLL driver updates ibias when
setting the rate); `0x50` (postdiv/lock) stayed the same.

GPLL is referenced only once in the DTB (`<0x24 0x1d>`), and its only consumer
is the GPU, so changing it does not affect other peripherals.

---

## 3. The real fix: `assigned-clocks`

The kit adds these properties to the GPU node:

```dts
assigned-clocks      = <0x24 0x1d>;   /* GPLL: phandle 0x24, CLK_GPLL = 0x1d */
assigned-clock-rates = <1100000000>;
```

`of_clk_set_defaults()` runs during device creation, before the GPU driver
probes. Because the PLL providers are built in and the GPU driver is a module
from `/vendor_dlkm`, the provider is always available at that point.
`clk_set_rate(gpll, 1100000000)` programs the PLL and nothing sets it back
afterwards.

If the rate change fails, the kernel only logs an error and the GPU stays at
850 MHz. It does not brick the device.

The OPP table is also rewritten so that:

- the top OPP frequency equals the GPLL rate;
- `devfreq` exposes the new frequency in `available_frequencies`;
- the top DVFS entry keeps cell `0x08`.

The voltage field is rewritten only for completeness; see
[`MEASUREMENTS.md`](MEASUREMENTS.md).

---

## 4. What the builder patches

`oc.py build` performs these steps:

1. Validates the input: 100 MiB, FDT magic at `0x2482040`, top OPP
   850 MHz @ 800 mV, top DVFS cell `0x08`, no existing `assigned-clock-rates`
   or `mali-supply`.
2. Parses the FDT structure block and locates the GPU node.
3. Appends the required property-name strings to the strings block.
4. Inserts the new properties just before the GPU node's `END_NODE` tag (the
   node's properties are already parsed, so existing offsets stay valid).
5. Rewrites the top entries of `operating-points` and `sprd,dvfs-lists`.
6. Updates the FDT header: `totalsize`, `off_dt_strings`, `size_dt_strings`,
   `size_dt_struct`.
7. Updates the SPRD wrapper (`+0x04`, `+0x20`) and the boot-header `dtb_size`
   at `0x834`.
8. Re-parses the output and verifies the structure and values.

Everything outside the FDT is copied byte-for-byte. `verify --stock` proves
this by comparing:

- bytes `0x000–0x833` (header before `dtb_size`);
- bytes `0x838–0x2481fff` (between header and wrapper);
- everything after the larger of the two FDTs.

### Reproducible hashes

| Build | SHA-256 |
|---|---|
| 1100 MHz / 1000 mV | `cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277` |
| 1100 MHz / 1200 mV | `76ba8995f01702a50c818b6040b52921032df752b57e31269dd9dcd4e03b8295` |
| 1100 MHz / 1200 mV + `mali-supply` | `02a90f8823221e5b72aa3aff269ac84da8bfca18db2a5ad658c2126e93edfec6` |
| 1600 MHz / 1200 mV + `mali-supply` | `fe21059f4f436f2a3b54aeae405b5f76d6f42da99ec33cc90e2a339102b0bd73` |

These are byte-identical to the reference images built during the original
investigation.

---

## 5. The `mali-supply` experiment

The Mali kbase driver (`mali_kbase_ums9230.ko`) has an optional regulator path:

- `power_control_init()` looks up optional supplies named **`mali`** and
  **`shadercores`**;
- `kbase_devfreq_target()` calls `devfreq_recommended_opp()`,
  `dev_pm_opp_get_voltage()`, `kbase_devfreq_opp_translate()`, then
  `regulator_set_voltage()` before changing frequency.

Stock DT only provides `gpu-supply` (the Unisoc path), so this code never ran.
`--mali-supply` adds:

```dts
mali-supply = <0x47>;   /* DCDC_GPU */
```

On device this works as designed at the driver level: `regulator.2` (`vddgpu`)
gains the consumer `23100000.gpu-mali` with `num_users=1`, and kbase does call
`regulator_set_voltage()`.

It still does not change the rail, because the hardware topdvfs engine
reprograms the PMIC. Writing 1200 mV directly through debugfs (with
`locken = 0x6e7f`) reads back 912 mV immediately. Treat `--mali-supply` as a
diagnostic variant only.

---

## 6. Why the rail is clamped

The GPU node references the topdvfs controller and its config:

```dts
topdvfs-controller   = <0x48>;
top_dvfs_cfg         = <0x4b 0x150 0x02>;
```

The controller (`topdvfsctrl@64014000`) has a `dcdc_mm` / `gpu-sys` subnode:

```dts
dcdc-subsys-tune-enable = <0x150 0x01 0x01>;
```

The voltage table used by that hardware engine is not the DT OPP table; it is
part of the DVFS configuration/efuse data (`nvmem-cells = <&gpu_bin>`). The
kernel only supplies the **cell index** (`0x04`–`0x08`); the engine picks the
rail voltage for that cell.

Measured rail per level:

| Level | Frequency | `DCDC_GPU/voltage` |
|---|---|---|
| 0 | 384 MHz | 750 mV |
| 1 | 512 MHz | 750 mV |
| 2 | 614.4 MHz | 750 mV |
| 3 | 768 MHz | 781 mV |
| 4 | 1.1 GHz (GPLL) | 912 mV |

A real 1.2 V rail would require disabling or reprogramming the GPU tune-enable
bits at `0x150` in topdvfs. That is outside the scope of a `vendor_boot` DT
patch and carries a much higher risk of hanging the device.

---

## 7. Verification model

`oc.py verify` is intentionally strict and boring:

- size and magic checks catch truncated or wrong-device images;
- header/wrapper checks catch a partially applied patch;
- `--stock` byte-range checks catch accidental changes outside the FDT;
- the GPU dump catches wrong OPP values, wrong DVFS cells and a wrong GPLL rate.

`build` runs the same checks internally before printing `verify: PASS`, so an
image that fails verification is never presented as good.
