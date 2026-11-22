#!/usr/bin/env python3
# Verify a serenity vendor_boot.img built with real_oc.py / real_oc_mali.py
# Usage: python3 verify_vendor_boot.py <image> [baseline]
# Default baseline: vendor_boot.img (same directory as this script).
import struct, sys, hashlib, os

FDT_OFF = 38281280          # serenity: FDT starts here (0x2482040)
WRAPPER = FDT_OFF - 64      # SPRD 64-byte wrapper
HDR_DTB_SIZE = 0x834        # boot header v4: dtb_size (little-endian)
TARGET = ("soc", "mm", "gpu@23100000")

def u32be(b, o): return struct.unpack_from(">I", b, o)[0]

def fdt_size(img):
    return u32be(img, WRAPPER + 0x20)

def parse_gpu(dtb):
    magic, total, off_struct, off_strings, off_rsv, ver, last, bcpu, \
        size_strings, size_struct = struct.unpack_from(">10I", dtb, 0)
    assert magic == 0xD00DFEED, "bad FDT magic"
    assert total == len(dtb), "FDT size mismatch"

    p, path, out = off_struct, [], {}
    while p < off_struct + size_struct:
        tag = u32be(dtb, p); p += 4
        if tag == 1:                                  # FDT_BEGIN_NODE
            e = dtb.index(b"\0", p)
            path.append(dtb[p:e].decode("latin1"))
            p = (e + 4) & ~3
        elif tag == 2:                                # FDT_END_NODE
            path.pop()
        elif tag == 3:                                # FDT_PROP
            ln, nameoff = struct.unpack_from(">II", dtb, p); p += 8
            if tuple(path[-3:]) == TARGET:
                e = dtb.index(b"\0", off_strings + nameoff)
                out[dtb[off_strings + nameoff:e].decode("latin1")] = dtb[p:p+ln]
            p = (p + ln + 3) & ~3
        elif tag == 9:                                # FDT_END
            break
    return out

def u32s(v):
    return list(struct.unpack(">%dI" % (len(v)//4), v[:len(v)//4*4]))

def show_gpu(props):
    print("GPU node: /soc/mm/gpu@23100000")
    ph = props.get("phandle")
    if ph: print("  phandle              : %#x" % u32s(ph)[0])
    gs = props.get("gpu-supply")
    if gs: print("  gpu-supply           : %#x" % u32s(gs)[0])
    ms = props.get("mali-supply")
    print("  mali-supply          : %s" % (("%#x" % u32s(ms)[0]) if ms else "(absent)"))
    ac = props.get("assigned-clocks")
    ar = props.get("assigned-clock-rates")
    if ac: print("  assigned-clocks      : %s" % ", ".join("%#x" % x for x in u32s(ac)))
    if ar: print("  assigned-clock-rates : %s" % ", ".join("%d" % x for x in u32s(ar)))
    op = props.get("operating-points")
    if op:
        v = u32s(op)
        print("  operating-points     :")
        for i in range(0, len(v), 2):
            print("    %7.1f MHz @ %4.0f mV" % (v[i]/1000.0, v[i+1]/1000.0))
    dl = props.get("sprd,dvfs-lists")
    if dl:
        v = u32s(dl)
        print("  sprd,dvfs-lists      :")
        for i in range(0, len(v), 4):
            print("    %7.1f MHz @ %4.0f mV  cell=%#x en=%d" %
                  (v[i]/1000.0, v[i+1]/1000.0, v[i+2], v[i+3]))

def main():
    if len(sys.argv) < 2:
        print(__doc__ or "usage: verify_vendor_boot.py <image> [baseline]")
        return 2
    img_path = sys.argv[1]
    base_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vendor_boot.img")

    img = open(img_path, "rb").read()
    ns = fdt_size(img)
    dtb = img[FDT_OFF:FDT_OFF + ns]
    print("image      : %s" % img_path)
    print("size       : %d bytes" % len(img))
    print("sha256     : %s" % hashlib.sha256(img).hexdigest())
    print("FDT offset : %#x (%d)" % (FDT_OFF, FDT_OFF))
    print("FDT size   : %d" % ns)
    print("wrapper+0x04 (64+FDT) : %d" % u32be(img, WRAPPER + 0x04))
    print("wrapper+0x20 (FDT)    : %d" % u32be(img, WRAPPER + 0x20))
    print("header 0x834 (64+FDT) : %d" % struct.unpack_from("<I", img, HDR_DTB_SIZE)[0])

    ok = True
    if len(img) != 104857600:
        print("WARN: expected 104857600 bytes"); ok = False

    show_gpu(parse_gpu(dtb))
    print()

    if not os.path.exists(base_path):
        print("baseline not found (%s); structural checks skipped" % base_path)
        return 0 if ok else 1
    base = open(base_path, "rb").read()
    if len(base) != len(img):
        print("FAIL: different file length vs baseline"); return 1

    ns0 = fdt_size(base)
    checks = []
    checks.append(("bytes 0x000-0x833 unchanged",
                   base[:HDR_DTB_SIZE] == img[:HDR_DTB_SIZE]))
    checks.append(("bytes 0x838-0x%x unchanged" % (WRAPPER - 1),
                   base[HDR_DTB_SIZE+4:WRAPPER] == img[HDR_DTB_SIZE+4:WRAPPER]))
    checks.append(("header 0x834 = 64 + FDT size",
                   struct.unpack_from("<I", img, HDR_DTB_SIZE)[0] == 64 + ns))
    checks.append(("wrapper +0x04 = 64 + FDT size",
                   u32be(img, WRAPPER + 0x04) == 64 + ns))
    checks.append(("wrapper +0x20 = FDT size",
                   u32be(img, WRAPPER + 0x20) == ns))
    end = max(ns0, ns)
    checks.append(("bytes after FDT unchanged",
                   base[FDT_OFF + end:] == img[FDT_OFF + end:]))
    for name, good in checks:
        print("%s %s" % ("OK  " if good else "FAIL", name))
        ok = ok and good
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
