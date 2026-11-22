# Safety and recovery

This kit modifies `vendor_boot.img`. A bad image can prevent the device from
booting, so read this before flashing.

**Validated on hardware: 1.1 GHz only.** Everything above that is experimental
and has failed on the test device.

---

## 1. Validated limits

| Setting | Status |
|---|---|
| Stock 850 MHz | safe baseline |
| **1.1 GHz GPLL** | **validated: boots, 0 GPU faults, stable** |
| 1.15 / 1.2 GHz | boots, screen artifacts under load — **not recommended** |
| 1.6 GHz | hangs at boot, `GPU fault 0x4002` — **do not flash** |
| OPP voltage > 1000 mV | does not raise the rail; no benefit |
| `mali-supply` | boots at 1.1 GHz, rail unchanged |

The rail is clamped by the topdvfs hardware engine. Raising the OPP voltage
does not raise the rail, so it cannot make a higher clock stable.

---

## 2. Before you flash

1. **Confirm the device.** This kit targets `serenity` (Redmi A5 / POCO C71,
   UMS9230E) only. Do not use it on another Unisoc device.
2. **Use the matching stock image.** The builder expects the exact 100 MiB
   layout and stock OPP values. Do not mix images from different firmware
   versions.
3. **Keep a stock image.** Copy `vendor_boot.img` somewhere safe (PC and SD
   card). This is your rollback.
4. **Back up data.** A bootloop can require a factory reset in the worst case.
5. **Charge the battery.** Do not flash at low battery.
6. **Know fastboot.** Test `adb reboot fastboot` and `fastboot devices` before
   you need them.
7. **Run `oc.py verify`.** Do not flash an image that fails verification.

The tool never flashes. You run every flash command yourself.

---

## 3. Flashing

```bash
adb reboot fastboot
fastboot devices
fastboot flash vendor_boot vendor_boot_oc_1100mhz_1000mv.img
fastboot reboot
```

Only `vendor_boot` is touched. Do not flash `boot`, `dtbo`, `super` or any
other partition for this overclock.

After boot, confirm the clock:

```bash
adb shell su -c 'cat /sys/class/devfreq/23100000.gpu/cur_freq'
# expected: 1100000000
```

---

## 4. Rollback

If the device still boots:

```bash
adb reboot fastboot
fastboot flash vendor_boot vendor_boot.img
fastboot reboot
```

If it does not boot:

1. Hold **Power + Volume Down** (or the fastboot key combo for this device)
   until fastboot appears.
2. Flash the stock `vendor_boot.img`.
3. Reboot.

If fastboot is not reachable, use the device's recovery/download mode. The
`vendor_boot` partition is independent of user data; restoring it does not
erase data by itself.

### Bootloop with the 1.6 GHz image

The known failure is a GPU fault at boot with a black screen and backlight on.
The device may keep soft-resetting. Force it into fastboot, flash stock
`vendor_boot.img`, then reboot. Do not keep booting the bad image.

---

## 5. Special warnings

### Do not flash CPU SML overclock images

CPU SML overclocking is dead on this Android 17 firmware. Only the raw
`sml-sign.bin` boots. Several SML images, including `sml_a17_stock.img`, have
bricked the test device. This kit does not touch `sml` or any CPU clock.

### Do not chase 1.2 V through the OPP table

The OPP voltage value is informational. The topdvfs engine sets the rail from
its own table. Editing `operating-points`, `sprd,dvfs-lists` or adding
`mali-supply` does not change it. The only way to a real 1.2 V rail is to
disable or reprogram topdvfs (`0x150` tune-enable bits), which this kit does
not do and does not support.

### Thermal and power

A +29% GPU clock increases power draw. Long gaming sessions will produce more
heat. If the device throttles or becomes unstable, go back to stock. Do not
stack this with CPU/GPU thermal or voltage modifications you do not understand.

### Anti-rollback and firmware updates

A firmware update can replace `vendor_boot` and remove the overclock. Re-check
the stock image layout before rebuilding after an update. Do not flash a
modified image from an older firmware onto a newer one.

---

## 6. The safety gate

`oc.py build` refuses frequencies above 1200 MHz or voltages above 1000 mV
unless `--i-know-the-risks` is passed:

```bash
python3 oc.py build --stock vendor_boot.img --freq-mhz 1600 \
    --gpll-mhz 1600 --volt-mv 1200 --i-know-the-risks
```

This flag is not an endorsement. It only confirms that you have read this
document. 1.6 GHz is known to hang the device.

The builder also refuses:

- non-stock images (top OPP not 850 MHz @ 800 mV);
- images whose top DVFS cell is not GPLL (`0x08`);
- images that already contain `assigned-clock-rates` or `mali-supply`;
- output paths that would overwrite the stock image;
- frequencies outside 850–2500 MHz, GPLL outside 100–3000 MHz, or voltage
  outside 400–1500 mV.

---

## 7. Liability

MIT License. The software is provided "as is", without warranty of any kind.
Overclocking voids warranties and can damage hardware. You flash at your own
risk. The author is not responsible for bricked devices, lost data or any other
damage.

If something goes wrong, restore the stock `vendor_boot.img` first and diagnose
from there.
