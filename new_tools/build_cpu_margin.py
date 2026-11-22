#!/usr/bin/env python3
# build_cpu_margin.py — add sprd,voltage-margin to apcpu-dvfs DTB on the 5.15 base.
# Offline only: prepares a vendor_boot image with a voltage margin (mV, signed).
# Negative margin = undervolt (safer); positive = overvolt (test carefully).

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DTC = Path("/home/hoang/Downloads/oc_gpu/dtc")
IMAGE = HERE / "vendor_boot.img"
IMAGE_SIZE = 104857600

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print(p.stdout)
        sys.exit(1)
    return p.stdout

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin-mv", type=int, default=-37,
                    help="Voltage margin in mV (signed). Negative = undervolt.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not IMAGE.is_file():
        sys.exit("missing %s" % IMAGE)
    img = IMAGE.read_bytes()
    if len(img) != IMAGE_SIZE:
        sys.exit("unexpected image size %d" % len(img))

    fdt_off = img.find(b"\xd0\x0d\xfe\xed")
    if fdt_off < 0:
        sys.exit("FDT magic not found")
    wrapper = fdt_off - 0x40
    if img[wrapper:wrapper + 4] != b"\xd7\xb7\xab\x1e":
        sys.exit("SPRD wrapper magic not found at %#x" % wrapper)

    old_fdt_size = int.from_bytes(img[fdt_off + 4:fdt_off + 8], "big")
    j = fdt_off + old_fdt_size
    while j < len(img) and img[j] == 0:
        j += 1
    pad = j - (fdt_off + old_fdt_size)

    work = HERE / ".work_cpu_margin"
    work.mkdir(exist_ok=True)
    fdt = work / "in.dtb"
    dts = work / "in.dts"
    raw = work / "out.raw.dtb"
    fdt.write_bytes(img[fdt_off:fdt_off + old_fdt_size])
    run([str(DTC), "-I", "dtb", "-O", "dts", "-o", str(dts), str(fdt)])
    text = dts.read_text()

    needle = "sprd,temp-threshold = <0x41>;"
    if text.count(needle) != 2:
        sys.exit("expected 2 sprd,temp-threshold, found %d" % text.count(needle))

    margin_u32 = args.margin_mv & 0xFFFFFFFF
    replacement = "sprd,temp-threshold = <0x41>;\n\t\t\t\tsprd,voltage-margin = <0x%x>;" % margin_u32
    text = text.replace(needle, replacement)

    if text.count("sprd,voltage-margin") < 2:
        sys.exit("failed to inject sprd,voltage-margin")

    dts.write_text(text)
    run([str(DTC), "-I", "dts", "-O", "dtb", "-o", str(raw), str(dts)])

    new_fdt = raw.read_bytes()
    if len(new_fdt) > old_fdt_size + pad:
        sys.exit("new FDT too large: %d > %d" % (len(new_fdt), old_fdt_size + pad))

    out = bytearray(img)
    # zero the old FDT region + pad, then write new FDT
    out[fdt_off:fdt_off + old_fdt_size + pad] = b"\x00" * (old_fdt_size + pad)
    out[fdt_off:fdt_off + len(new_fdt)] = new_fdt
    # update FDT totalsize field (big-endian) at fdt_off+4
    out[fdt_off + 4:fdt_off + 8] = len(new_fdt).to_bytes(4, "big")
    out_bytes = bytes(out)

    out_name = args.out or "vendor_boot_cpu_margin_%dmv.img" % args.margin_mv
    out_path = HERE / out_name
    out_path.write_bytes(out_bytes)
    print("wrote %s (%d bytes)" % (out_path, len(out_bytes)))
    print("margin = %d mV (0x%x)" % (args.margin_mv, margin_u32))

    verify_fdt = work / "verify.dtb"
    verify_fdt.write_bytes(new_fdt)
    v = subprocess.run([str(DTC), "-I", "dtb", "-O", "dts", "-o", str(work / "verify.dts"), str(verify_fdt)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if v.returncode != 0:
        print(v.stdout)
        sys.exit("verify failed")
    vt = (work / "verify.dts").read_text()
    if "sprd,voltage-margin" not in vt:
        sys.exit("verification: property missing")
    print("verification OK: sprd,voltage-margin present")

if __name__ == "__main__":
    main()
