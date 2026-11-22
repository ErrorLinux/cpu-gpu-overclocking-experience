#!/usr/bin/env python3
# build_allfreq.py — build "all GPU OPP levels 1.0–1.6 GHz" experiment images.
#
# Base: the vendor_boot.img found next to this script (kernel 5.15 base of the
#        Redmi A5 / serenity, FDT at 0x20b9040, SPRD wrapper at FDT-0x40).
#
# Method (no mkbootimg repack — the rest of the 100 MiB image is untouched):
#   1. find FDT by magic 0xd00dfeed
#   2. dtc decompile -> edit GPU node -> dtc recompile
#   3. write the new FDT back at the same offset (zero the obsolete tail)
#   4. patch boot-header dtb_size (0x834), wrapper +0x04 and +0x20
#   5. re-parse the result and print the GPU node for verification
#
# OPP levels (kHz / uV, informational — rail is clamped by topdvfs):
#   384/512/614.4/768 (fixed PLL cells 04..07) +
#   1000/1100/1200/1300/1400/1500/1600 (GPLL cell 08)
#
# Each output gets exactly ONE assigned-clock-rates value (the --rate argument).
# Flash ONE image at a time. The 5.15 base will NOT boot on Android 17 stock
# ramdisk without the matching kernel — you said you will flash it yourself.

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DTC = Path("/home/hoang/Downloads/oc_gpu/dtc")
IMAGE = HERE / "vendor_boot.img"
IMAGE_SIZE = 104857600

# (freq_khz, volt_uv, dvfs_cell) — cell 0x08 = GPLL
TABLE = [
    (384000,  700000, 0x04),
    (512000,  750000, 0x05),
    (614400,  750000, 0x06),
    (768000,  800000, 0x07),
    (1000000, 900000, 0x08),
    (1100000, 950000, 0x08),
    (1200000, 975000, 0x08),
    (1300000, 1000000, 0x08),
    (1400000, 1025000, 0x08),
    (1500000, 1050000, 0x08),
    (1600000, 1100000, 0x08),
]
MAX_IDX = len(TABLE) - 1  # 0x0a

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        sys.exit(p.stdout)
    return p.stdout

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate-mhz", type=int, required=True,
                    help="GPLL rate baked into assigned-clock-rates (1000..1600)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    if not IMAGE.is_file():
        sys.exit("missing %s" % IMAGE)
    rate_hz = args.rate_mhz * 1000 * 1000
    if not 1000 <= args.rate_mhz <= 3000:
        sys.exit("--rate-mhz out of range")

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
    pad = 0
    j = fdt_off + old_fdt_size
    while j < len(img) and img[j] == 0:
        j += 1
    pad = j - (fdt_off + old_fdt_size)
    print("base   : %s" % IMAGE)
    print("FDT    : offset %#x, size %d, padding free %d" %
          (fdt_off, old_fdt_size, pad))

    work = HERE / (".work_allfreq")
    work.mkdir(exist_ok=True)
    fdt = work / "in.dtb"
    dts = work / "in.dts"
    raw = work / "out.raw.dtb"
    fdt.write_bytes(img[fdt_off:fdt_off + old_fdt_size])
    run([str(DTC), "-I", "dtb", "-O", "dts", "-o", str(dts), str(fdt)])

    text = dts.read_text()

    # Locate the GPU node precisely (path /soc/mm/gpu@23100000).
    m = re.search(r"\n(\s+)gpu@23100000\s*\{([^}]*)\};", text)
    if not m or "sprd,mali-natt" not in m.group(2):
        sys.exit("GPU node not found in DTS")
    indent, body = m.group(1), m.group(2)

    opp = " ".join("0x%x 0x%x" % (f, v) for f, v, _ in TABLE)
    dvfs = " ".join("0x%x 0x%x 0x%02x 0x01" % (f, v, c)
                    for f, v, c in TABLE)

    body = re.sub(r"operating-points\s*=\s*<[^>]+>;",
                  "operating-points = <%s>;" % opp, body)
    body = re.sub(r"sprd,dvfs-lists\s*=\s*<[^>]+>;",
                  "sprd,dvfs-lists = <%s>;" % dvfs, body)
    body = re.sub(r"sprd,dvfs-range-max\s*=\s*<[^>]+>;",
                  "sprd,dvfs-range-max = <0x%02x>;" % MAX_IDX, body)
    body = re.sub(r"sprd,dvfs-scene-extreme\s*=\s*<[^>]+>;",
                  "sprd,dvfs-scene-extreme = <0x%02x>;" % MAX_IDX, body)

    # GPLL phandle/cell: last pair of the clocks property.
    cm = re.search(r"clocks\s*=\s*<([^>]+)>;", body)
    if not cm:
        sys.exit("clocks property not found")
    cells = [x.lower() for x in cm.group(1).split()]
    def as_int(s):
        return int(s, 16) if s.startswith("0x") else int(s)
    nums = [as_int(x) for x in cells]
    if len(nums) % 2 or len(nums) < 4:
        sys.exit("bad clocks property")
    gpll_phandle, gpll_cell = nums[-2], nums[-1]
    print("GPLL   : phandle %#x cell %#x (rate %d MHz)"
          % (gpll_phandle, gpll_cell, args.rate_mhz))

    if "assigned-clock-rates" not in body:
        add = ("\n%s\tassigned-clocks = <0x%x 0x%x>;\n"
               "%s\tassigned-clock-rates = <%d>;"
               % (indent, gpll_phandle, gpll_cell, indent, rate_hz))
        body = body.rstrip("\n") + add + "\n" + indent
    else:
        body = re.sub(r"assigned-clock-rates\s*=\s*<[^>]+>;",
                      "assigned-clock-rates = <%d>;" % rate_hz, body)

    new_node = "\n%sgpu@23100000 {\n%s};" % (indent, body)
    text = text[:m.start()] + new_node + text[m.end():]
    dts.write_text(text)

    run([str(DTC), "-I", "dts", "-O", "dtb", "-o", str(raw), str(dts)])
    new_fdt = raw.read_bytes()
    if len(new_fdt) > old_fdt_size + pad:
        sys.exit("new FDT %d bytes does not fit (%d available)"
                 % (len(new_fdt), old_fdt_size + pad))
    print("FDT    : %d -> %d bytes" % (old_fdt_size, len(new_fdt)))

    out = bytearray(img)
    out[fdt_off:fdt_off + len(new_fdt)] = new_fdt
    for i in range(fdt_off + len(new_fdt), fdt_off + old_fdt_size):
        out[i] = 0
    out[wrapper + 4:wrapper + 8] = (64 + len(new_fdt)).to_bytes(4, "big")
    out[wrapper + 0x20:wrapper + 0x24] = len(new_fdt).to_bytes(4, "big")
    out[0x834:0x838] = (64 + len(new_fdt)).to_bytes(4, "little")
    Path(args.out).write_bytes(out)

    # Verify by decompiling the written image again.
    verify_dtb = work / "verify.dtb"
    verify_dtb.write_bytes(out[fdt_off:fdt_off + len(new_fdt)])
    dtsv = run([str(DTC), "-I", "dtb", "-O", "dts", str(verify_dtb)])
    vm = re.search(r"gpu@23100000\s*\{[^}]*\};", dtsv)
    print()
    print(vm.group(0))
    print()
    print("image  : %s (%d bytes)" % (args.out, len(out)))

    if not args.keep_work:
        for p in work.iterdir():
            p.unlink()
        work.rmdir()

if __name__ == "__main__":
    main()
