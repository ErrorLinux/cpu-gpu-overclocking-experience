#!/usr/bin/env python3
# Ainz GPU OC Kit — real GPU frequency overclock for Redmi A5 / POCO C71 (serenity)
# Author: Ainz
# License: MIT
#
# Builds a modified vendor_boot.img that forces GPLL to a chosen rate through
# the GPU node's assigned-clocks / assigned-clock-rates properties. The OPP
# table is updated as well, but on serenity the GPU rail is controlled by the
# hardware topdvfs engine; the OPP voltage field is informational only.
#
# Tested on: Redmi A5 / POCO C71 (serenity), Unisoc UMS9230E / T7250,
#            Mali-G57 MP1, Android 17 vendor_boot (100 MiB, FDT @ 0x2482040).

import argparse
import hashlib
import os
import struct
import sys

VERSION = "1.0.0"
AUTHOR = "Ainz"
DEVICE = "Redmi A5 / POCO C71 (serenity, Unisoc UMS9230E / T7250)"

FDT_OFF = 0x2482040          # 38281280
WRAPPER = FDT_OFF - 0x40     # 0x2482000 (SPRD 64-byte wrapper)
HDR_DTB_SIZE = 0x834         # boot header v4: dtb_size (little-endian)
IMAGE_SIZE = 104857600       # 100 MiB
TARGET_PATH = ("soc", "mm", "gpu@23100000")
STOCK_TOP = (850000, 800000)  # top OPP of the stock table (kHz, uV)

FDT_BEGIN = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

GPLL_PHANDLE = 0x24
GPLL_CELL = 0x1D
DCDC_GPU_PHANDLE = 0x47


class KitError(Exception):
    pass


def fail(msg):
    raise KitError(msg)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def be32(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def read_image(path):
    try:
        with open(path, "rb") as f:
            img = f.read()
    except OSError as exc:
        fail("cannot read %s: %s" % (path, exc))

    if len(img) != IMAGE_SIZE:
        fail("%s: expected %d bytes, got %d (not a serenity vendor_boot.img?)"
             % (path, IMAGE_SIZE, len(img)))
    if be32(img, FDT_OFF) != 0xD00DFEED:
        fail("%s: no FDT magic at %#x (not a serenity vendor_boot.img?)"
             % (path, FDT_OFF))

    dtb_size = be32(img, WRAPPER + 0x20)
    if dtb_size < 40 or FDT_OFF + dtb_size > len(img):
        fail("%s: invalid FDT size %d" % (path, dtb_size))
    return img, dtb_size


def u32s(value):
    return list(struct.unpack(">%dI" % (len(value) // 4), value[:len(value) // 4 * 4]))


def parse_gpu(img, dtb_size):
    dtb = img[FDT_OFF:FDT_OFF + dtb_size]
    magic, total, off_struct, off_strings, off_rsv, ver, last, bcpu, \
        size_strings, size_struct = struct.unpack_from(">10I", dtb, 0)
    if magic != 0xD00DFEED or total != dtb_size:
        fail("corrupt FDT header")

    props = {}
    names = set()
    pos, path = off_struct, []
    end = off_struct + size_struct
    while pos < end:
        tag = be32(dtb, pos)
        pos += 4
        if tag == FDT_BEGIN:
            nul = dtb.index(b"\0", pos)
            path.append(dtb[pos:nul].decode("latin1"))
            pos = (nul + 4) & ~3
        elif tag == FDT_END_NODE:
            if not path:
                fail("corrupt FDT: unbalanced END_NODE")
            path.pop()
        elif tag == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", dtb, pos)
            pos += 8
            nul = dtb.index(b"\0", off_strings + nameoff)
            name = dtb[off_strings + nameoff:nul].decode("latin1")
            if tuple(path[-3:]) == TARGET_PATH:
                props[name] = dtb[pos:pos + length]
                names.add(name)
            pos = (pos + length + 3) & ~3
        elif tag == FDT_NOP:
            continue
        elif tag == FDT_END:
            break

    if "operating-points" not in props or "sprd,dvfs-lists" not in props:
        fail("GPU OPP properties not found — unsupported image")
    return props, names


def gpu_info(img, dtb_size):
    props, names = parse_gpu(img, dtb_size)
    op = u32s(props["operating-points"])
    dl = u32s(props["sprd,dvfs-lists"])
    if len(op) < 2 or len(op) % 2:
        fail("bad operating-points length")
    if len(dl) < 4 or len(dl) % 4:
        fail("bad sprd,dvfs-lists length")

    return {
        "props": props,
        "names": names,
        "opps": [(op[i], op[i + 1]) for i in range(0, len(op), 2)],
        "levels": [(dl[i], dl[i + 1], dl[i + 2], dl[i + 3])
                   for i in range(0, len(dl), 4)],
        "gpll": u32s(props["assigned-clock-rates"])[0]
        if "assigned-clock-rates" in props else None,
        "mali": u32s(props["mali-supply"])[0]
        if "mali-supply" in props else None,
        "gpu_supply": u32s(props["gpu-supply"])[0]
        if "gpu-supply" in props else None,
        "phandle": u32s(props["phandle"])[0] if "phandle" in props else None,
    }


def print_gpu(info):
    props = info["props"]
    print("GPU node: /soc/mm/gpu@23100000")
    if info["phandle"] is not None:
        print("  phandle              : %#x" % info["phandle"])
    if info["gpu_supply"] is not None:
        print("  gpu-supply           : %#x" % info["gpu_supply"])
    print("  mali-supply          : %s"
          % (("%#x" % info["mali"]) if info["mali"] is not None else "(absent)"))
    if info["gpll"] is not None:
        print("  assigned-clock-rates : %d (%g MHz)"
              % (info["gpll"], info["gpll"] / 1e6))
    print("  operating-points     :")
    for freq, volt in info["opps"]:
        print("    %8.1f MHz @ %4.0f mV" % (freq / 1000.0, volt / 1000.0))
    print("  sprd,dvfs-lists      :")
    for freq, volt, cell, en in info["levels"]:
        print("    %8.1f MHz @ %4.0f mV  cell=%#04x en=%d"
              % (freq / 1000.0, volt / 1000.0, cell, en))


def patch_image(img, dtb_size, freq_khz, volt_uv, gpll_hz, mali_supply):
    dtb = bytearray(img[FDT_OFF:FDT_OFF + dtb_size])
    magic, totalsize, off_struct, off_strings, off_rsv, ver, last, bcpu, \
        size_strings, size_struct = struct.unpack_from(">10I", dtb, 0)
    if magic != 0xD00DFEED or totalsize != dtb_size:
        fail("corrupt FDT header")
    struct_blk = dtb[off_struct:off_struct + size_struct]
    strings_blk = dtb[off_strings:off_strings + size_strings]

    def sname(rel):
        nul = dtb.index(b"\0", rel)
        return dtb[rel:nul].decode("latin1")

    gpu_end = None
    prop_pos = {}
    names = set()
    pos, path = off_struct, []
    while True:
        tag = be32(dtb, pos)
        pos += 4
        if tag == FDT_BEGIN:
            nul = dtb.index(b"\0", pos)
            path.append(dtb[pos:nul].decode("latin1"))
            pos = (nul + 4) & ~3
        elif tag == FDT_END_NODE:
            if tuple(path[-3:]) == TARGET_PATH:
                gpu_end = pos - 4
            path.pop()
        elif tag == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", dtb, pos)
            pos += 8
            if tuple(path[-3:]) == TARGET_PATH:
                name = sname(off_strings + nameoff)
                names.add(name)
                if name in ("operating-points", "sprd,dvfs-lists"):
                    prop_pos[name] = (pos, length)
            pos = (pos + length + 3) & ~3
        elif tag == FDT_END:
            break

    if gpu_end is None:
        fail("GPU node not found")
    if "operating-points" not in prop_pos or "sprd,dvfs-lists" not in prop_pos:
        fail("GPU OPP properties not found — unsupported image")

    op_off, op_len = prop_pos["operating-points"]
    dl_off, dl_len = prop_pos["sprd,dvfs-lists"]
    if op_len != 40 or dl_len != 80:
        fail("unexpected OPP table size (op=%d, dvfs=%d) — stock serenity has "
             "5 entries (40/80 bytes)" % (op_len, dl_len))
    if struct.unpack_from(">II", dtb, op_off + 32) != STOCK_TOP:
        fail("top OPP is not stock 850 MHz @ 800 mV — input must be a stock "
             "vendor_boot.img")
    if struct.unpack_from(">II", dtb, dl_off + 64) != STOCK_TOP:
        fail("top DVFS entry is not stock 850 MHz @ 800 mV — input must be a "
             "stock vendor_boot.img")
    if struct.unpack_from(">I", dtb, dl_off + 64 + 8)[0] != 0x08:
        fail("top DVFS entry does not use the GPLL cell (0x08)")

    if "assigned-clock-rates" in names:
        fail("input already has assigned-clock-rates — use a clean stock image")
    if mali_supply and "mali-supply" in names:
        fail("input already has mali-supply — use a clean stock image")

    # Reuse existing strings when possible, otherwise append them.
    string_map = {}
    p2 = 0
    while p2 < len(strings_blk):
        nul = strings_blk.index(b"\0", p2)
        string_map[strings_blk[p2:nul].decode("latin1")] = p2
        p2 = nul + 1

    sn = string_map.get("assigned-clocks")
    if sn is None:
        sn = len(strings_blk)
        strings_blk += b"assigned-clocks\0"
    sr = string_map.get("assigned-clock-rates")
    if sr is None:
        sr = len(strings_blk)
        strings_blk += b"assigned-clock-rates\0"
    ms = None
    if mali_supply:
        ms = string_map.get("mali-supply")
        if ms is None:
            ms = len(strings_blk)
            strings_blk += b"mali-supply\0"

    ins = gpu_end - off_struct
    props = struct.pack(">III", FDT_PROP, 8, sn) + \
        struct.pack(">II", GPLL_PHANDLE, GPLL_CELL)
    props += struct.pack(">III", FDT_PROP, 4, sr) + struct.pack(">I", gpll_hz)
    if mali_supply:
        props += struct.pack(">III", FDT_PROP, 4, ms) + \
            struct.pack(">I", DCDC_GPU_PHANDLE)

    struct_new = struct_blk[:ins] + props + struct_blk[ins:]
    new_off_strings = off_struct + len(struct_new)
    new_total = new_off_strings + len(strings_blk)
    if new_total > dtb_size + 798:
        fail("patched FDT does not fit in the vendor_boot page padding")

    header = struct.pack(">10I", magic, new_total, off_struct,
                         new_off_strings, off_rsv, ver, last, bcpu,
                         len(strings_blk), len(struct_new))
    fdt = bytearray(header + dtb[40:off_struct] + struct_new + strings_blk)

    # The new properties are inserted after the OPP properties, so their
    # offsets are still valid in the new FDT.
    struct.pack_into(">II", fdt, op_off + 32, freq_khz, volt_uv)
    struct.pack_into(">II", fdt, dl_off + 64, freq_khz, volt_uv)
    if struct.unpack_from(">I", fdt, dl_off + 64 + 8)[0] != 0x08:
        fail("internal error: top DVFS cell changed")

    out = bytearray(img)
    out[FDT_OFF:FDT_OFF + new_total] = fdt
    struct.pack_into(">I", out, WRAPPER + 0x04, 64 + new_total)
    struct.pack_into(">I", out, WRAPPER + 0x20, new_total)
    struct.pack_into("<I", out, HDR_DTB_SIZE, 64 + new_total)
    return bytes(out), new_total


def structure_checks(img, dtb_size, stock=None, stock_size=None):
    checks = []
    checks.append(("image size is %d bytes" % IMAGE_SIZE,
                   len(img) == IMAGE_SIZE))
    checks.append(("FDT magic at %#x" % FDT_OFF,
                   be32(img, FDT_OFF) == 0xD00DFEED))
    checks.append(("header 0x834 = 64 + FDT size",
                   struct.unpack_from("<I", img, HDR_DTB_SIZE)[0] == 64 + dtb_size))
    checks.append(("wrapper +0x04 = 64 + FDT size",
                   be32(img, WRAPPER + 0x04) == 64 + dtb_size))
    checks.append(("wrapper +0x20 = FDT size",
                   be32(img, WRAPPER + 0x20) == dtb_size))

    if stock is not None:
        checks.append(("same file length as stock", len(stock) == len(img)))
        checks.append(("bytes 0x000-0x833 unchanged",
                       stock[:HDR_DTB_SIZE] == img[:HDR_DTB_SIZE]))
        checks.append(("bytes 0x838-%#x unchanged" % (WRAPPER - 1),
                       stock[HDR_DTB_SIZE + 4:WRAPPER] ==
                       img[HDR_DTB_SIZE + 4:WRAPPER]))
        end = max(stock_size, dtb_size)
        checks.append(("bytes after FDT unchanged",
                       stock[FDT_OFF + end:] == img[FDT_OFF + end:]))
    return checks


def read_stock(path):
    img, size = read_image(path)
    info = gpu_info(img, size)
    if info["opps"][-1] != STOCK_TOP:
        fail("%s: top OPP is not stock 850 MHz @ 800 mV" % path)
    if info["gpll"] is not None:
        fail("%s: image already has assigned-clock-rates (not stock)" % path)
    if info["mali"] is not None:
        fail("%s: image already has mali-supply (not stock)" % path)
    return img, size, info


def cmd_build(args):
    freq_mhz = args.freq_mhz
    gpll_mhz = args.gpll_mhz if args.gpll_mhz is not None else freq_mhz
    volt_mv = args.volt_mv

    if freq_mhz < 850 or freq_mhz > 2500:
        fail("--freq-mhz must be between 850 and 2500 (stock is 850)")
    if gpll_mhz < 100 or gpll_mhz > 3000:
        fail("--gpll-mhz must be between 100 and 3000")
    if volt_mv < 400 or volt_mv > 1500:
        fail("--volt-mv must be between 400 and 1500")

    if (freq_mhz > 1200 or volt_mv > 1000) and not args.i_know_the_risks:
        fail("refusing unsafe values without --i-know-the-risks.\n"
             "  On serenity, 1.15/1.2 GHz already produce screen artifacts and\n"
             "  1.6 GHz hangs the GPU at boot (GPU fault 0x4002). The GPU rail is\n"
             "  controlled by topdvfs; a higher OPP voltage does not raise it.")

    freq_khz = freq_mhz * 1000
    gpll_hz = gpll_mhz * 1000000
    volt_uv = volt_mv * 1000

    stock, stock_size, stock_info = read_stock(args.stock)

    out_path = args.out
    if not out_path:
        suffix = "_mali" if args.mali_supply else ""
        out_path = "vendor_boot_oc_%dmhz_%dmv%s.img" % (
            freq_mhz, volt_mv, suffix)

    if os.path.abspath(out_path) == os.path.abspath(args.stock):
        fail("output path must not overwrite the stock image")

    out, new_size = patch_image(stock, stock_size, freq_khz, volt_uv,
                                gpll_hz, args.mali_supply)
    try:
        with open(out_path, "wb") as f:
            f.write(out)
    except OSError as exc:
        fail("cannot write %s: %s" % (out_path, exc))

    info = gpu_info(out, new_size)
    checks = structure_checks(out, new_size, stock, stock_size)
    ok = all(good for _, good in checks)
    if info["opps"][-1] != (freq_khz, volt_uv):
        ok = False
    if info["levels"][-1][:2] != (freq_khz, volt_uv):
        ok = False
    if info["gpll"] != gpll_hz:
        ok = False
    if args.mali_supply and info["mali"] != DCDC_GPU_PHANDLE:
        ok = False
    if not args.mali_supply and info["mali"] is not None:
        ok = False

    print("Ainz GPU OC Kit %s" % VERSION)
    print("device      : %s" % DEVICE)
    print("stock       : %s" % args.stock)
    print("output      : %s" % out_path)
    print("top OPP     : %.1f MHz @ %d mV" % (freq_mhz, volt_mv))
    print("GPLL        : %d MHz (real GPU clock)" % gpll_mhz)
    if gpll_mhz != freq_mhz:
        print("warning     : GPLL and top OPP differ; the real clock is GPLL")
    print("mali-supply : %s" % ("yes (DCDC_GPU)" if args.mali_supply else "no"))
    print("FDT         : %d bytes (stock %d)" % (new_size, stock_size))
    print("SHA-256     : %s" % sha256(out))
    print("verify      : %s" % ("PASS" if ok else "FAIL"))
    print("")
    print("note: on serenity the GPU rail is controlled by topdvfs; the OPP")
    print("      voltage is informational. See docs/MEASUREMENTS.md.")
    return 0 if ok else 1


def cmd_verify(args):
    img, size = read_image(args.image)
    stock = stock_size = None
    if args.stock:
        stock, stock_size = read_image(args.stock)[:2]

    print("image       : %s" % args.image)
    print("size        : %d bytes" % len(img))
    print("sha256      : %s" % sha256(img))
    print("FDT offset  : %#x (%d)" % (FDT_OFF, FDT_OFF))
    print("FDT size    : %d" % size)
    print("wrapper+0x04: %d" % be32(img, WRAPPER + 0x04))
    print("wrapper+0x20: %d" % be32(img, WRAPPER + 0x20))
    print("header 0x834: %d" % struct.unpack_from("<I", img, HDR_DTB_SIZE)[0])
    print("")

    print_gpu(gpu_info(img, size))
    print("")
    checks = structure_checks(img, size, stock, stock_size)
    for name, good in checks:
        print("%s %s" % ("OK  " if good else "FAIL", name))
    print("")
    ok = all(good for _, good in checks)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="oc.py",
        description="Ainz GPU OC Kit — real GPLL overclock for the Redmi A5 / "
                    "POCO C71 (serenity). Author: %s." % AUTHOR,
        epilog="The tool never flashes anything. You flash the output yourself.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + VERSION + " (Ainz)")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build a modified vendor_boot.img")
    b.add_argument("--stock", default="vendor_boot.img",
                   help="stock vendor_boot.img (default: %(default)s)")
    b.add_argument("--out", help="output image (default: auto-named)")
    b.add_argument("--freq-mhz", type=int, required=True,
                   help="target top frequency and GPLL rate in MHz (e.g. 1100)")
    b.add_argument("--gpll-mhz", type=int,
                   help="GPLL rate in MHz (default: same as --freq-mhz)")
    b.add_argument("--volt-mv", type=int, default=800,
                   help="top OPP voltage in mV (informational only; default: "
                        "%(default)s)")
    b.add_argument("--mali-supply", action="store_true",
                   help="add mali-supply = <&DCDC_GPU> (experimental)")
    b.add_argument("--i-know-the-risks", action="store_true",
                   help="allow >1200 MHz or >1000 mV")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="verify an image and print its OPP table")
    v.add_argument("image")
    v.add_argument("--stock", help="stock image for byte-level comparison")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KitError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
