#!/usr/bin/env python3
"""SML OC packer - magic64 signature-preserving overclock image builder.

Patches the DVFS freq/volt tables of the sml image at RUNTIME (shellcode
applies edits after secure-boot verify passes), so the signed payload stays
byte-identical and no key is needed.

Examples (WSL):
  python3 sml_oc_pack.py --profile max -o sml_oc.img
  python3 sml_oc_pack.py --profile stock -o sml_test.img
  python3 sml_oc_pack.py --profile max --set C1:6=2100000@1012500 -o sml_oc.img
  python3 sml_oc_pack.py --profile max --c0 "614400@700000,768000@700000,..." -o out.img
"""
import argparse
import hashlib
import struct
import sys

C0_OFF, C1_OFF = 0x199d8, 0x17dc8
C0_ROWS, C1_ROWS = 8, 7
MIN_VOLT, MAX_VOLT, MAX_FREQ = 650000, 1050000, 2400000
DEFAULT_LOAD_BASE = 0xB0000000
DEFAULT_INPUT = '/mnt/d/download/serenity_global_images_A15.0.31.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'

STOCK_C0 = [(614400, 700000), (768000, 700000), (884000, 700000), (1040000, 700000),
            (1228800, 762500), (1378000, 815625), (1536000, 868750), (1612000, 896875)]
STOCK_C1 = [(768000, 750000), (1040000, 750000), (1228800, 750000), (1404000, 780000),
            (1536000, 820000), (1690000, 870000), (1820000, 910000)]
MAX_C0 = [(614400, 700000), (768000, 700000), (884000, 700000), (1040000, 700000),
          (1228800, 762500), (1378000, 815625), (1612000, 975000), (1820000, 1050000)]
MAX_C1 = [(768000, 750000), (1040000, 750000), (1228800, 762500), (1404000, 780000),
          (1536000, 820000), (1950000, 980000), (2210000, 1050000)]

_SHELLCODE_TEMPLATE = [
    0x90000009, 0x9100412a, 0xd2a0004b, 0xf280000b, 0xd280000c, 0xeb0b018d,
    0x540000e2, 0xf86c794d, 0xf82c792d, 0xd508711f, 0xd5033fdf, 0x9100058c,
    0x17fffff9, 0x90000009, 0x91020129, 0xb840452a, 0xb400016a, 0xb840452b,
    0xd280000c, 0xeb0b018d, 0x54ffff62, 0xb840452d, 0xb800454d, 0xd508711f,
    0xd5033fdf, 0x9100058c, 0x17fffff9, 0x17fbffe1,
]


def build_shellcode(size):
    n = size // 8
    w = list(_SHELLCODE_TEMPLATE)
    imm = 0x200 - (0x210 + size)
    w[0] = (0x10000000 | ((imm & 3) << 29)
            | (((imm >> 2) & 0x7FFFF) << 5) | 9)
    w[2] = 0xD2A00000 | (((n >> 16) & 0xFFFF) << 5) | 11
    w[3] = 0xF2800000 | ((n & 0xFFFF) << 5) | 11
    w[13] = (0x10000000 | ((0x3C & 3) << 29)
             | (((0x3C >> 2) & 0x7FFFF) << 5) | 9)
    w[14] = 0xD503201F
    off = -(size + 0x7C)
    w[27] = 0x14000000 | ((off >> 2) & 0x3FFFFFF)
    return struct.pack('<28I', *w)


def parse_table(s, n):
    rows = []
    for tok in s.replace(';', ',').split(','):
        tok = tok.strip()
        if not tok:
            continue
        f, _, v = tok.partition('@')
        rows.append((int(f, 0), int(v, 0)))
    if len(rows) != n:
        raise SystemExit('table has %d rows, expected %d: %r' % (len(rows), n, s))
    return rows


def validate_table(name, new, stock):
    errs, warns = [], []
    if len(new) != len(stock):
        errs.append('%s row count changed' % name)
    for i in range(1, len(new)):
        if new[i][0] <= new[i - 1][0]:
            errs.append('%s row %d: freq not strictly increasing' % (name, i))
    for i, (f, v) in enumerate(new):
        if f > MAX_FREQ:
            errs.append('%s row %d: freq %d > hard cap %d' % (name, i, f, MAX_FREQ))
        if not MIN_VOLT <= v <= MAX_VOLT:
            errs.append('%s row %d: volt %d outside [%d, %d]'
                        % (name, i, v, MIN_VOLT, MAX_VOLT))
    if new[0] != stock[0]:
        warns.append('%s min operating point changed (%s -> %s)'
                     % (name, stock[0], new[0]))
    if new[-1][0] <= stock[-1][0]:
        warns.append('%s max freq %d does not exceed stock %d (no OC in this table)'
                     % (name, new[-1][0], stock[-1][0]))
    return errs, warns


def pack_magic(data, size, groups, load_base, add_len):
    foot_off = 0x200 + size
    footer = bytearray(data[foot_off:foot_off + 0x60])
    if footer[0:7] != b'SIMGHDR' or struct.unpack_from('<Q', footer, 0x18)[0] != 0x200:
        raise SystemExit('SIMGHDR footer not found / already patched')
    patch_data = b''
    for off, words in groups:
        patch_data += struct.pack('<II', load_base + off, len(words))
        patch_data += struct.pack('<%dI' % len(words), *words)
    patch_data += struct.pack('<I', 0)
    shell = build_shellcode(size)
    if len(shell) + len(patch_data) > add_len - 0x10:
        raise ValueError('add_len %#x too small' % add_len)
    out = bytearray()
    hdr = bytearray(data[0:0x200])
    struct.pack_into('<I', hdr, 0x30, size + add_len)
    out += hdr
    jump = 0x14000000 | (((size + 0x10) // 4) & 0x3FFFFFF)
    out += struct.pack('<I', jump) + b'\x00' * 0x0C
    out += data[0x200:0x200 + size]
    magic = bytearray(add_len - 0x10)
    magic[0:len(shell)] = shell
    magic[len(shell):len(shell) + len(patch_data)] = patch_data
    out += magic
    struct.pack_into('<Q', footer, 0x18, 0x210)
    for so, oo in [(0x20, 0x28), (0x30, 0x38), (0x40, 0x48), (0x50, 0x58)]:
        if struct.unpack_from('<Q', footer, so)[0]:
            struct.pack_into('<Q', footer, oo,
                             struct.unpack_from('<Q', footer, oo)[0] + add_len)
    out += footer
    out += data[foot_off + 0x60:]
    return bytes(out)


def check(cond, name, fails):
    print('  [%s] %s' % ('OK ' if cond else 'FAIL', name))
    if not cond:
        fails.append(name)
    return cond


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-i', '--input', default=DEFAULT_INPUT, help='stock sml image (DHTB)')
    ap.add_argument('-o', '--output', default='sml_oc.img', help='output image')
    ap.add_argument('--profile', choices=['stock', 'max'], default='max',
                    help='stock = no patch (pipeline test), max = validated OC tables')
    ap.add_argument('--c0', help='full C0 table "freq@volt,freq@volt,..." (%d rows)' % C0_ROWS)
    ap.add_argument('--c1', help='full C1 table (%d rows)' % C1_ROWS)
    ap.add_argument('--oc', action='append', default=[], metavar='TBL=FREQ@VOLT',
                    help='raise top OPP of table, e.g. --oc C1=2210000@1050000 (repeatable)')
    ap.add_argument('--set', action='append', default=[], metavar='TBL:IDX=FREQ@VOLT',
                    help='row override, e.g. C1:6=2100000@1012500 (repeatable)')
    ap.add_argument('--load-base', type=lambda x: int(x, 0), default=DEFAULT_LOAD_BASE)
    ap.add_argument('--part-size', type=lambda x: int(x, 0), default=0x100000)
    ap.add_argument('--force', action='store_true',
                    help='skip payload fingerprint / stock-table sanity checks')
    args = ap.parse_args()

    data = bytearray(open(args.input, 'rb').read())
    if data[0:4] != b'DHTB':
        raise SystemExit('not a DHTB image: %s' % args.input)
    size = struct.unpack_from('<I', data, 0x30)[0]
    payload = bytes(data[0x200:0x200 + size])
    sha = hashlib.sha256(payload).hexdigest()
    print('input : %s\npayload: %#x bytes  sha256=%s' % (args.input, size, sha))
    if sha != KNOWN_PAYLOAD_SHA256 and not args.force:
        raise SystemExit('unknown sml build (fingerprint mismatch), use --force to override')

    def read_table(off, n):
        return [struct.unpack_from('<II', payload, off + 8 * i) for i in range(n)]

    stock = {'C0': read_table(C0_OFF, C0_ROWS), 'C1': read_table(C1_OFF, C1_ROWS)}
    for name, ref in (('C0', STOCK_C0), ('C1', STOCK_C1)):
        if stock[name] != ref and not args.force:
            raise SystemExit('%s table does not match known stock, use --force' % name)
        if stock[name] != ref:
            print('  note: %s differs from known stock: %s' % (name, stock[name]))

    new = dict(stock)
    if args.profile == 'max':
        new = {'C0': list(MAX_C0), 'C1': list(MAX_C1)}
    if args.c0:
        new['C0'] = parse_table(args.c0, C0_ROWS)
    if args.c1:
        new['C1'] = parse_table(args.c1, C1_ROWS)
    for spec in args.oc:
        tbl, _, fv = spec.partition('=')
        tbl = tbl.upper()
        if tbl not in new:
            raise SystemExit('--oc: unknown table %r (use C0 or C1)' % tbl)
        f, _, v = fv.partition('@')
        new[tbl][-1] = (int(f, 0), int(v, 0))
    for spec in args.set:
        tbl, _, rest = spec.partition(':')
        idx_s, _, fv = rest.partition('=')
        tbl, idx = tbl.upper(), int(idx_s)
        f, _, v = fv.partition('@')
        new[tbl][idx] = (int(f, 0), int(v, 0))

    errs, warns = [], []
    for name in ('C0', 'C1'):
        e, w = validate_table(name, new[name], stock[name])
        errs += e
        warns += w
    for w in warns:
        print('  [warn] %s' % w)
    if errs:
        for e in errs:
            print('  [FAIL] %s' % e)
        raise SystemExit('table validation failed')

    groups = []
    offs = {'C0': C0_OFF, 'C1': C1_OFF}
    for name in ('C0', 'C1'):
        print('== %s @payload+%#x' % (name, offs[name]))
        for i, (sn, nn) in enumerate(zip(stock[name], new[name])):
            mark = '' if sn == nn else '   <-- %s -> %s' % (sn, nn)
            print('   [%d] %d kHz %7d mV%s' % (i, nn[0], nn[1], mark))
        if new[name] != stock[name]:
            groups.append((offs[name], [w for pair in new[name] for w in pair]))

    patch_len = sum(8 + 4 * len(g[1]) for g in groups) + 4
    add_len = ((0x10 + 0x70 + patch_len + 0xFF) // 0x100) * 0x100
    if add_len < 0x100:
        add_len = 0x100

    target = args.part_size - add_len
    if len(data) > target:
        raise SystemExit('input %#x too big for partition %#x with add_len %#x'
                         % (len(data), args.part_size, add_len))
    data += b'\x00' * (target - len(data))
    out = pack_magic(data, size, groups, args.load_base, add_len)
    if len(out) != args.part_size:
        raise SystemExit('output %#x != partition size %#x' % (len(out), args.part_size))

    print('== validation')
    fails = []
    d = out
    check(d[0:4] == b'DHTB', 'DHTB magic', fails)
    check(struct.unpack_from('<I', d, 0x30)[0] == size + add_len, 'DHTB size updated', fails)
    jw = struct.unpack_from('<I', d, 0x200)[0]
    check((jw >> 26) == 0b000101 and 0x200 + (jw & 0x3FFFFFF) * 4 == 0x210 + size,
          'entry B -> shellcode', fails)
    check(d[0x210:0x210 + size] == payload, 'payload byte-identical (verify passes)', fails)
    sim = 0x200 + size + add_len
    check(sim + 0x100 <= len(d) and d[sim:sim + 7] == b'SIMGHDR', 'footer moved', fails)
    check(struct.unpack_from('<Q', d, sim + 0x18)[0] == 0x210, 'footer payload_offset=0x210', fails)
    check(struct.unpack_from('<Q', d, sim + 0x10)[0] == size, 'footer payload_size unchanged', fails)
    check(struct.unpack_from('<Q', d, sim + 0x28)[0] == 0x204a0 + add_len,
          'footer cert_offset shifted', fails)
    check(d[8:0x28] == data[8:0x28], 'DHTB hash field untouched', fails)
    check(len(d) == args.part_size, 'image == partition size (%#x)' % len(d), fails)

    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
        md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        sh = 0x210 + size
        ins = list(md.disasm(d[sh:sh + 0x70], sh))
        check(len(ins) == 28, 'shellcode disassembles', fails)
        if len(ins) == 28:
            check(ins[0].mnemonic == 'adr' and ins[0].op_str.endswith('#0x200'),
                  'adr x9 -> entry', fails)
            check(ins[1].mnemonic == 'add' and '#0x10' in ins[1].op_str,
                  'src = entry+0x10', fails)
            check(ins[7].mnemonic == 'ldr' and ins[8].mnemonic == 'str'
                  and ins[9].mnemonic == 'ic' and ins[10].mnemonic == 'isb',
                  'copy loop intact', fails)
            check(ins[13].mnemonic == 'adr' and ins[13].op_str.endswith(hex(sh + 0x70)),
                  'adr x9 -> patch_data', fails)
            check(ins[14].mnemonic == 'nop', 'w14 nop', fails)
            check(ins[27].mnemonic == 'b' and ins[27].op_str.endswith('#0x200'),
                  'b -> entry', fails)
    except ImportError:
        print('  [skip] capstone not available - shellcode disasm checks skipped')

    mem = bytearray(d)
    mem[0x200:0x200 + size] = d[0x210:0x210 + size]
    expected = bytearray(payload)
    for off, words in groups:
        for i, w in enumerate(words):
            struct.pack_into('<I', mem, 0x200 + off + 4 * i, w)
            struct.pack_into('<I', expected, off + 4 * i, w)
    check(bytes(mem[0x200:0x200 + size]) == bytes(expected),
          'runtime sim: copy+patch == expected', fails)
    check(mem[0x210 + size:0x210 + size + 0x70] == d[0x210 + size:0x210 + size + 0x70],
          'shellcode untouched by copy', fails)

    open(args.output, 'wb').write(d)
    if fails:
        raise SystemExit('%d checks FAILED, output NOT trusted' % len(fails))
    print('wrote %s (%d bytes) - ALL CHECKS PASS' % (args.output, len(d)))
    print('\nflash : spd_dump exec_addr 0x65015f08 fdl fdl1-dl.bin 0x65000800 '
          'fdl fdl2-dl.bin 0x9efffe00 exec w sml_a "%s" w sml_b "%s" reset'
          % (args.output, args.output))
    print('restore: same command with stock sml-sign.bin (or backup/sml_a.bin)')


if __name__ == '__main__':
    main()
