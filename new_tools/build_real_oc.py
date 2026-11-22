#!/usr/bin/env python3
# build_real_oc.py — "real" GPU OC (assigned-clocks reprograms GPLL) on the
# kernel 5.15 base image, mirroring Ainz-GPU-OC-Kit/oc.py (5 OPP levels,
# top OPP rewritten, GPLL programmed once at boot). No OPP-table-only fakery.

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DTC = Path("/home/hoang/Downloads/oc_gpu/dtc")
IMAGE = HERE / "vendor_boot.img"
IMAGE_SIZE = 104857600

# 5-level table mirroring the kit's stable build (lower 4 = stock fixed PLLs)
BASE_LEVELS = [
    (384000,  700000, 0x04),
    (512000,  750000, 0x05),
    (614400,  750000, 0x06),
    (768000,  800000, 0x07),
]

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        sys.exit(p.stdout)
    return p.stdout

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate-mhz", type=int, default=1100)
    ap.add_argument("--volt-mv", type=int, default=1000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--mali-supply", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    if not IMAGE.is_file():
        sys.exit("missing %s" % IMAGE)
    rate_hz = args.rate_mhz * 1000 * 1000
    volt_uv = args.volt_mv * 1000
    if not 850 <= args.rate_mhz <= 3000:
        sys.exit("--rate-mhz out of range")
    if not 400 <= args.volt_mv <= 1500:
        sys.exit("--volt-mv out of range")

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

    LEVELS = BASE_LEVELS + [(args.rate_mhz * 1000, volt_uv, 0x08)]

    work = HERE / ".work_realoc"
    work.mkdir(exist_ok=True)
    fdt = work / "in.dtb"
    dts = work / "in.dts"
    raw = work / "out.raw.dtb"
    fdt.write_bytes(img[fdt_off:fdt_off + old_fdt_size])
    run([str(DTC), "-I", "dtb", "-O", "dts", "-o", str(dts), str(fdt)])
    text = dts.read_text()

    m = re.search(r"\n(\s+)gpu@23100000\s*\{([^}]*)\};", text)
    if not m or "sprd,mali-natt" not in m.group(2):
        sys.exit("GPU node not found in DTS")
    indent, body = m.group(1), m.group(2)

    opp = " ".join("0x%x 0x%x" % (f, v) for f, v, _ in LEVELS)
    dvfs = " ".join("0x%x 0x%x 0x%02x 0x01" % (f, v, c)
                    for f, v, c in LEVELS)

    body = re.sub(r"operating-points\s*=\s*<[^>]+>;",
                  "operating-points = <%s>;" % opp, body)
    body = re.sub(r"sprd,dvfs-lists\s*=\s*<[^>]+>;",
                  "sprd,dvfs-lists = <%s>;" % dvfs, body)

    cm = re.search(r"clocks\s*=\s*<([^>]+)>;", body)
    if not cm:
        sys.exit("clocks property not found")
    nums = [int(x, 16) if x.startswith("0x") else int(x)
            for x in cm.group(1).split()]
    if len(nums) % 2 or len(nums) < 4:
        sys.exit("bad clocks property")
    gpll_phandle, gpll_cell = nums[-2], nums[-1]

    if "assigned-clock-rates" not in body:
        add = ("\n%s\tassigned-clocks = <0x%x 0x%x>;\n"
               "%s\tassigned-clock-rates = <%d>;"
               % (indent, gpll_phandle, gpll_cell, indent, rate_hz))
        body = body.rstrip("\n") + add + "\n" + indent
    else:
        body = re.sub(r"assigned-clock-rates\s*=\s*<[^>]+>;",
                      "assigned-clock-rates = <%d>;" % rate_hz, body)

    if args.mali_supply and "mali-supply" not in body:
        # try to reuse the DCDC_GPU phandle from the OPP phandle convention:
        # serenity uses 0x47; the 5.15 base uses a different phandle. Detect
        # DCDC_GPU by searching the topdvfs controller node is too complex;
        # look for a regulator phandle named in the node's gpu-supply instead.
        ms = re.search(r"gpu-supply\s*=\s*<([^>]+)>;", body)
        if not ms:
            sys.exit("gpu-supply not found; cannot add mali-supply automatically")
        # Do not guess a different phandle; reuse gpu-supply value as a hint
        # only if the user explicitly passes --mali-phandle.
        sys.exit("--mali-supply requires --mali-phandle on this base image")

    new_node = "\n%sgpu@23100000 {\n%s};" % (indent, body)
    text = text[:m.start()] + new_node + text[m.end():]
    dts.write_text(text)

    run([str(DTC), "-I", "dts", "-O", "dtb", "-o", str(raw), str(dts)])
    new_fdt = raw.read_bytes()
    if len(new_fdt) > old_fdt_size + pad:
        sys.exit("new FDT %d bytes does not fit (%d available)"
                 % (len(new_fdt), old_fdt_size + pad))

    out_name = args.out
    if not out_name:
        suffix = "_mali" if args.mali_supply else ""
        out_name = "vendor_boot_oc_%dmhz_%dmv%s.img" % (
            args.rate_mhz, args.volt_mv, suffix)
    out_path = HERE / out_name

    out = bytearray(img)
    out[fdt_off:fdt_off + len(new_fdt)] = new_fdt
    for i in range(fdt_off + len(new_fdt), fdt_off + old_fdt_size):
        out[i] = 0
    out[wrapper + 4:wrapper + 8] = (64 + len(new_fdt)).to_bytes(4, "big")
    out[wrapper + 0x20:wrapper + 0x24] = len(new_fdt).to_bytes(4, "big")
    out[0x834:0x838] = (64 + len(new_fdt)).to_bytes(4, "little")
    out_path.write_bytes(out)

    # verify
    verify_dtb = work / "verify.dtb"
    verify_dtb.write_bytes(out[fdt_off:fdt_off + len(new_fdt)])
    dtsv = run([str(DTC), "-I", "dtb", "-O", "dts", str(verify_dtb)])
    vm = re.search(r"gpu@23100000\s*\{[^}]*\};", dtsv)
    print(vm.group(0))
    print()
    print("base   : %s" % IMAGE)
    print("FDT    : %d -> %d bytes" % (old_fdt_size, len(new_fdt)))
    print("GPLL   : phandle %#x cell %#x -> %d MHz" %
          (gpll_phandle, gpll_cell, args.rate_mhz))
    print("image  : %s (%d bytes)" % (out_path, len(out)))

    if not args.keep_work:
        for p in work.iterdir():
            p.unlink()
        work.rmdir()

if __name__ == "__main__":
    main()
