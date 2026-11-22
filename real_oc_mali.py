#!/usr/bin/env python3
import struct, sys

SRC, DST, FREQ_KHZ, GPLL_HZ, VOLT_UV = sys.argv[1], sys.argv[2], \
    int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
TARGET_PATH = ("soc", "mm", "gpu@23100000")
FDT_BEGIN, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_FIN = 1, 2, 3, 4, 9

img = bytearray(open(SRC, "rb").read())
FDT_OFF = 38281280
WRAPPER = FDT_OFF - 64
DTB_SIZE = struct.unpack_from(">I", img, WRAPPER + 0x20)[0]
print("FDT at %#x, size %d" % (FDT_OFF, DTB_SIZE))

dtb = bytearray(img[FDT_OFF:FDT_OFF + DTB_SIZE])
magic, totalsize, off_struct, off_strings, off_rsv, ver, last, bcpu, \
    size_strings, size_struct = struct.unpack_from(">10I", dtb, 0)
assert magic == 0xD00DFEED and totalsize == DTB_SIZE
struct_blk = dtb[off_struct:off_struct + size_struct]
strings_blk = dtb[off_strings:off_strings + size_strings]

def sname(rel):
    e = dtb.index(b"\0", rel)
    return dtb[rel:e].decode()

gpu_end = [None]
prop_pos = {}
p, path = off_struct, []
while True:
    tag = struct.unpack_from(">I", dtb, p)[0]; p += 4
    if tag == FDT_BEGIN:
        e = dtb.index(b"\0", p); path.append(dtb[p:e].decode()); p = (e + 4) & ~3
    elif tag == FDT_END_NODE:
        if tuple(path[-3:]) == TARGET_PATH:
            gpu_end[0] = p - 4
        path.pop()
    elif tag == FDT_PROP:
        length, nameoff = struct.unpack_from(">II", dtb, p); p += 8
        if tuple(path[-3:]) == TARGET_PATH:
            nm = sname(off_strings + nameoff)
            if nm in ("operating-points", "sprd,dvfs-lists"):
                prop_pos[nm] = (p, length)
        p = (p + length + 3) & ~3
    elif tag == FDT_FIN:
        break
ins = gpu_end[0] - off_struct
op_off, op_len = prop_pos["operating-points"]
dl_off, dl_len = prop_pos["sprd,dvfs-lists"]
assert op_len == 40 and dl_len == 80

names = {}
p2 = 0
while p2 < len(strings_blk):
    e = strings_blk.index(b"\0", p2)
    names[strings_blk[p2:e].decode()] = p2
    p2 = e + 1
SN = names.get("assigned-clocks")
if SN is None:
    SN = len(strings_blk); strings_blk += b"assigned-clocks\0"
SR = names.get("assigned-clock-rates")
if SR is None:
    SR = len(strings_blk); strings_blk += b"assigned-clock-rates\0"
MS = names.get("mali-supply")
if MS is None:
    MS = len(strings_blk); strings_blk += b"mali-supply\0"

props  = struct.pack(">III", FDT_PROP, 8, SN) + struct.pack(">II", 0x24, 0x1d)
props += struct.pack(">III", FDT_PROP, 4, SR) + struct.pack(">I", GPLL_HZ)
props += struct.pack(">III", FDT_PROP, 4, MS) + struct.pack(">I", 0x47)  # DCDC_GPU
struct_new = struct_blk[:ins] + props + struct_blk[ins:]
new_off_strings = off_struct + len(struct_new)
new_total = new_off_strings + len(strings_blk)
assert new_total <= DTB_SIZE + 798
header = struct.pack(">10I", magic, new_total, off_struct, new_off_strings,
                     off_rsv, ver, last, bcpu, len(strings_blk), len(struct_new))
fdt = bytearray(header + dtb[40:off_struct] + struct_new + strings_blk)

assert struct.unpack_from(">II", dtb, op_off + 32) == (850000, 800000)
assert struct.unpack_from(">II", dtb, dl_off + 64) == (850000, 800000)
struct.pack_into(">II", fdt, op_off + 32, FREQ_KHZ, VOLT_UV)
struct.pack_into(">II", fdt, dl_off + 64, FREQ_KHZ, VOLT_UV)
assert struct.unpack_from(">I", fdt, dl_off + 64 + 8)[0] == 0x08

out = bytearray(img)
out[FDT_OFF:FDT_OFF + new_total] = fdt
struct.pack_into(">I", out, WRAPPER + 0x04, 64 + new_total)
struct.pack_into(">I", out, WRAPPER + 0x20, new_total)
struct.pack_into("<I", out, 0x834, 64 + new_total)
open(DST, "wb").write(out)
print("wrote %s (%d bytes), FDT totalsize %d" % (DST, len(out), new_total))
