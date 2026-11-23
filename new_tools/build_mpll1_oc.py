#!/usr/bin/env python3
"""Patch mpll1 node in vendor_boot DTB: force channel 4 (A75 max) to 2.21 GHz.

Uses the same byte-level DTB reassembly as build_allfreq.py, so the rest of the
100 MiB image is untouched.
"""
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DTC = Path('/home/hoang/Downloads/oc_gpu/dtc')
IMAGE = HERE / 'vendor_boot.img'

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode:
        raise SystemExit(p.stdout)
    return p.stdout

def main():
    img = IMAGE.read_bytes()
    fdt_off = img.find(b'\xd0\x0d\xfe\xed')
    wrapper = fdt_off - 0x40
    assert img[wrapper:wrapper+4] == b'\xd7\xb7\xab\x1e'
    old_size = int.from_bytes(img[fdt_off+4:fdt_off+8], 'big')
    j = fdt_off + old_size
    while j < len(img) and img[j] == 0:
        j += 1
    pad = j - (fdt_off + old_size)

    work = HERE / '.work_mpll1'
    work.mkdir(exist_ok=True)
    fdt = work / 'in.dtb'; dts = work / 'in.dts'; raw = work / 'out.dtb'
    fdt.write_bytes(img[fdt_off:fdt_off+old_size])
    run([str(DTC), '-I', 'dtb', '-O', 'dts', '-o', str(dts), str(fdt)])
    text = dts.read_text()

    # mpll1 node: compatible = "sprd,ums9230-g3-pll", has #clock-cells = <0x1>
    m = re.search(r'\n(\s+)mpll1\s*\{([^}]*)\};', text)
    if not m or 'g3-pll' not in m.group(2):
        raise SystemExit('mpll1 node not found')
    indent, body = m.group(1), m.group(2)
    pm = re.search(r'phandle\s*=\s*<([^>]+)>;', body)
    if not pm:
        raise SystemExit('mpll1 phandle not found')
    ph = pm.group(1).strip()
    print('mpll1 phandle:', ph)

    rate = 2210000000  # Hz — channel 4 target (85 * 26 MHz)
    new_props = ('\n%s\tassigned-clocks = <%s 0x4>;'
                 '\n%s\tassigned-clock-rates = <%d>;' % (indent, ph, indent, rate))
    body = body.rstrip('\n') + new_props + '\n' + indent
    new_node = '\n%smpll1 {\n%s};' % (indent, body)
    text = text[:m.start()] + new_node + text[m.end():]
    dts.write_text(text)

    run([str(DTC), '-I', 'dts', '-O', 'dtb', '-o', str(raw), str(dts)])
    nf = raw.read_bytes()
    if len(nf) > old_size + pad:
        raise SystemExit('new FDT %d > available %d' % (len(nf), old_size + pad))
    out = bytearray(img)
    out[fdt_off:fdt_off+len(nf)] = nf
    for i in range(fdt_off+len(nf), fdt_off+old_size):
        out[i] = 0
    out[wrapper+4:wrapper+8] = (64 + len(nf)).to_bytes(4, 'big')
    out[wrapper+0x20:wrapper+0x24] = len(nf).to_bytes(4, 'big')
    out[0x834:0x838] = (64 + len(nf)).to_bytes(4, 'little')
    dest = HERE / 'vendor_boot_mpll1_2210.img'
    dest.write_bytes(out)
    print('FDT %d -> %d, wrote %s' % (old_size, len(nf), dest))

    verify = work / 'v.dtb'
    verify.write_bytes(out[fdt_off:fdt_off+len(nf)])
    v = run([str(DTC), '-I', 'dtb', '-O', 'dts', str(verify)])
    vm = re.search(r'mpll1\s*\{[^}]*\};', v)
    print(vm.group(0))

if __name__ == '__main__':
    main()
