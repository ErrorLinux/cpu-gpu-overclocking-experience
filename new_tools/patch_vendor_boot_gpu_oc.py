#!/usr/bin/env python3
"""
patch_vendor_boot_gpu_oc.py
--------------------------------------------------------------------------------
Universal GPU Overclock Patcher for Unisoc Android vendor_boot images.

Replaces the stock Mali GPU OPP table with the real hardware frequencies from
ums9230-clk.ko (GPLL synthesizer table: 900 MHz, 1.1 GHz, 1.3 GHz, 1.5 GHz, 1.6 GHz)
and adjusts voltages accordingly with PMIC SC2730 step accuracy.

Features:
- Unpacks vendor_boot.img (v3/v4).
- Decompiles internal DTB (supports Android DTBO header 0xd7b7ab1e and raw FDT 0xd00dfeed).
- Patches operating-points, sprd,dvfs-lists, sprd,dvfs-range-max, sprd,dvfs-scene-extreme.
- Recompiles DTB using dtc and re-wraps with valid DTBO header.
- Repacks vendor_boot.img with mkbootimg.py preserving kernel offsets, cmdline, and bootconfig.
- Re-signs with AVB (avbtool) matching the original partition size and fingerprints.
--------------------------------------------------------------------------------
"""

import sys
import os
import shutil
import subprocess
import struct
import re
import argparse

# Full hardware frequency table from ums9230-clk.ko & architecture
# (Frequency in kHz, Voltage in uV, Clock Parent Index, Vsel Mode)
UMS9230_FREQ_TABLE = [
    {"freq_khz": 384000,  "volt_uv": 700000,  "clk_parent": 4, "desc": "384 MHz (TWPLL-384M base)"},
    {"freq_khz": 512000,  "volt_uv": 750000,  "clk_parent": 5, "desc": "512 MHz (TWPLL-512M base)"},
    {"freq_khz": 614400,  "volt_uv": 750000,  "clk_parent": 6, "desc": "614.4 MHz (LPLL-614M4 base)"},
    {"freq_khz": 768000,  "volt_uv": 800000,  "clk_parent": 7, "desc": "768 MHz (TWPLL-768M base)"},
    {"freq_khz": 900000,  "volt_uv": 850000,  "clk_parent": 8, "desc": "900 MHz (GPLL ftable[0])"},
    {"freq_khz": 1100000, "volt_uv": 950000,  "clk_parent": 8, "desc": "1100 MHz / 1.1 GHz (GPLL ftable[1])"},
    {"freq_khz": 1300000, "volt_uv": 1000000, "clk_parent": 8, "desc": "1300 MHz / 1.3 GHz (GPLL ftable[2])"},
    {"freq_khz": 1500000, "volt_uv": 1050000, "clk_parent": 8, "desc": "1500 MHz / 1.5 GHz (GPLL ftable[3])"},
    {"freq_khz": 1600000, "volt_uv": 1100000, "clk_parent": 8, "desc": "1600 MHz / 1.6 GHz (GPLL ftable[4])"},
]

def find_tool(name, candidate_paths):
    for p in candidate_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    which = shutil.which(name)
    if which:
        return which
    return None

def detect_tools(args):
    tools = {}
    tools["dtc"] = args.dtc or find_tool("dtc", [
        "/usr/bin/dtc",
        "/root/android-kernel/build/kernel/build-tools/path/linux-x86/dtc",
    ])
    tools["unpack_bootimg"] = args.unpack_bootimg or find_tool("unpack_bootimg.py", [
        "/root/android-kernel/tools/mkbootimg/unpack_bootimg.py",
    ])
    tools["mkbootimg"] = args.mkbootimg or find_tool("mkbootimg.py", [
        "/root/android-kernel/tools/mkbootimg/mkbootimg.py",
    ])
    tools["avbtool"] = args.avbtool or find_tool("avbtool", [
        "/root/android-kernel/build/kernel/build-tools/path/linux-x86/avbtool",
        "/usr/bin/avbtool",
    ])

    missing = [k for k, v in tools.items() if not v]
    if missing:
        sys.exit(f"[-] Error: Required tool(s) not found: {missing}. Specify with command line flags.")
    return tools

def unpack_vendor_boot(img_path, work_dir, unpack_py):
    print(f"[*] Unpacking vendor_boot: {img_path}")
    os.makedirs(work_dir, exist_ok=True)
    cmd = [sys.executable, unpack_py, "--boot_img", img_path, "--out", work_dir]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.exit(f"[-] unpack_bootimg failed:\n{p.stderr}")
    return p.stdout

def parse_unpack_info(stdout_text):
    info = {
        "header_version": 4,
        "page_size": 4096,
        "kernel_offset": "0x00008000",
        "ramdisk_offset": "0x05400000",
        "tags_offset": "0x00000100",
        "dtb_offset": "0x01f00000",
        "base": "0x00000000",
        "vendor_cmdline": "",
    }
    for line in stdout_text.splitlines():
        line = line.strip()
        if "vendor boot image header version:" in line:
            info["header_version"] = int(line.split(":")[-1].strip())
        elif "page size:" in line:
            info["page_size"] = int(line.split(":")[-1].strip(), 16)
        elif "kernel load address:" in line:
            info["kernel_offset"] = line.split(":")[-1].strip()
        elif "ramdisk load address:" in line:
            info["ramdisk_offset"] = line.split(":")[-1].strip()
        elif "kernel tags load address:" in line:
            info["tags_offset"] = line.split(":")[-1].strip()
        elif "dtb address:" in line:
            info["dtb_offset"] = line.split(":")[-1].strip()
        elif "vendor command line args:" in line:
            info["vendor_cmdline"] = line.split(":", 1)[-1].strip()
    return info

def decompile_dtb(raw_dtb_path, dts_path, dtc_bin):
    with open(raw_dtb_path, "rb") as f:
        magic = f.read(4)

    is_dtbo_table = (magic == b"\xd7\xb7\xab\x1e")
    if is_dtbo_table:
        print("[*] Detected Android DTBO Table Header (magic 0xd7b7ab1e).")
        with open(raw_dtb_path, "rb") as f:
            hdr = f.read(64)
        _, total_size, _, _, _, _, _, _ = struct.unpack(">8I", hdr[:32])
        dt_size, dt_offset = struct.unpack(">2I", hdr[32:40])
        print(f"[*] Extracting inner FDT (size: {dt_size} bytes at offset 0x{dt_offset:x})...")
        with open(raw_dtb_path, "rb") as f:
            f.seek(dt_offset)
            fdt_data = f.read(dt_size)
        fdt_tmp = dts_path + ".fdt.tmp"
        with open(fdt_tmp, "wb") as f:
            f.write(fdt_data)
        src_for_dtc = fdt_tmp
    else:
        print("[*] Detected Raw Flattened Device Tree (FDT).")
        src_for_dtc = raw_dtb_path

    cmd = [dtc_bin, "-I", "dtb", "-O", "dts", src_for_dtc, "-o", dts_path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.exit(f"[-] dtc decompile failed:\n{p.stderr}")
    print(f"[+] Decompiled DTB -> DTS: {dts_path}")
    return is_dtbo_table

def build_opp_table(max_freq_mhz, all_freqs):
    max_freq_khz = max_freq_mhz * 1000
    if all_freqs:
        levels = UMS9230_FREQ_TABLE[:]
        max_idx = 0
        for i, l in enumerate(levels):
            if l["freq_khz"] <= max_freq_khz:
                max_idx = i
    else:
        levels = [l for l in UMS9230_FREQ_TABLE if l["freq_khz"] <= max_freq_khz]
        max_idx = len(levels) - 1

    return levels, max_idx

def patch_dts_file(dts_path, levels, max_idx):
    with open(dts_path, "r") as f:
        content = f.read()

    # Find GPU node (sprd,mali-*)
    gpu_pattern = re.compile(r"(\s+gpu@[0-9a-fA-F]+\s*\{[^}]+compatible\s*=\s*\"sprd,mali-[^\"]+\"[^}]+\};)", re.DOTALL)
    m = gpu_pattern.search(content)
    if not m:
        sys.exit("[-] Error: Mali GPU node (sprd,mali-*) not found in DTS!")

    gpu_node_text = m.group(1)

    # Detect GPLL parent index from clocks property
    gpll_idx = 8
    clk_match = re.search(r"clocks\s*=\s*<([^>]+)>;", gpu_node_text)
    if clk_match:
        cells = [int(x, 16) if x.startswith("0x") else int(x) for x in clk_match.group(1).split()]
        num_pairs = len(cells) // 2
        if num_pairs >= 9:
            gpll_idx = num_pairs - 1

    print(f"[*] Detected GPLL clock parent index in GPU node: 0x{gpll_idx:02x}")

    # Build OPP and DVFS list strings
    opp_tokens = []
    dvfs_tokens = []
    for l in levels:
        freq = l["freq_khz"]
        volt = l["volt_uv"]
        clk = l["clk_parent"]
        if clk >= 8:
            clk = gpll_idx
        opp_tokens.append(f"0x{freq:x} 0x{volt:x}")
        dvfs_tokens.append(f"0x{freq:x} 0x{volt:x} 0x{clk:02x} 0x01")

    opp_str = " ".join(opp_tokens)
    dvfs_str = " ".join(dvfs_tokens)

    print("\n" + "="*60)
    print("New Frequency & Voltage Table:")
    print("="*60)
    for i, l in enumerate(levels):
        tag = " [ACTIVE MAX]" if i == max_idx else ""
        print(f"  Level {i}: {l['freq_khz'] // 1000:4d} MHz ({l['freq_khz']} kHz) @ {l['volt_uv'] / 1000.0:6.1f} mV (0x{l['volt_uv']:x}) - {l['desc']}{tag}")
    print(f"  sprd,dvfs-range-max: <0x{max_idx:02x}>")
    print(f"  sprd,dvfs-scene-extreme: <0x{max_idx:02x}>")
    print("="*60 + "\n")

    def replacer(match):
        node = match.group(0)
        node = re.sub(r"operating-points\s*=\s*<[^>]+>;", f"operating-points = <{opp_str}>;", node)
        node = re.sub(r"sprd,dvfs-lists\s*=\s*<[^>]+>;", f"sprd,dvfs-lists = <{dvfs_str}>;", node)
        node = re.sub(r"sprd,dvfs-range-max\s*=\s*<[^>]+>;", f"sprd,dvfs-range-max = <0x{max_idx:02x}>;", node)
        node = re.sub(r"sprd,dvfs-scene-extreme\s*=\s*<[^>]+>;", f"sprd,dvfs-scene-extreme = <0x{max_idx:02x}>;", node)
        return node

    patched_content = gpu_pattern.sub(replacer, content)

    with open(dts_path, "w") as f:
        f.write(patched_content)
    print(f"[+] Patched DTS with updated OPP and DVFS tables.")

def compile_dtb(dts_path, out_dtb_path, dtc_bin, was_dtbo_table):
    print(f"[*] Compiling DTS -> DTB using dtc...")
    raw_compiled_fdt = out_dtb_path + ".raw.fdt"
    cmd = [dtc_bin, "-I", "dts", "-O", "dtb", dts_path, "-o", raw_compiled_fdt]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.exit(f"[-] dtc compile failed:\n{p.stderr}")

    with open(raw_compiled_fdt, "rb") as f:
        fdt_bytes = f.read()

    if was_dtbo_table:
        print("[*] Re-wrapping DTB in Android DTBO Table Header (0xd7b7ab1e)...")
        hdr = struct.pack(">8I", 0xd7b7ab1e, len(fdt_bytes) + 64, 32, 32, 1, 32, 2048, 0)
        entry = struct.pack(">8I", len(fdt_bytes), 64, 0, 0, 0, 0, 0, 0)
        final_dtb = hdr + entry + fdt_bytes
    else:
        final_dtb = fdt_bytes

    with open(out_dtb_path, "wb") as f:
        f.write(final_dtb)
    print(f"[+] Final DTB created: {out_dtb_path} ({len(final_dtb)} bytes)")

def repack_vendor_boot(work_dir, out_img_path, info, mkbootimg_py):
    print(f"[*] Repacking vendor_boot image with mkbootimg.py...")
    cmd = [
        sys.executable, mkbootimg_py,
        "--header_version", str(info["header_version"]),
        "--vendor_boot", out_img_path,
        "--vendor_ramdisk", os.path.join(work_dir, "vendor_ramdisk"),
        "--dtb", os.path.join(work_dir, "dtb"),
        "--vendor_cmdline", info["vendor_cmdline"],
        "--base", info["base"],
        "--kernel_offset", info["kernel_offset"],
        "--ramdisk_offset", info["ramdisk_offset"],
        "--tags_offset", info["tags_offset"],
        "--dtb_offset", info["dtb_offset"],
        "--pagesize", str(info["page_size"]),
    ]

    bootconfig_path = os.path.join(work_dir, "bootconfig")
    if os.path.isfile(bootconfig_path):
        cmd.extend(["--vendor_bootconfig", bootconfig_path])

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.exit(f"[-] mkbootimg repack failed:\n{p.stderr}")
    print(f"[+] Repacked raw vendor_boot image: {out_img_path}")

def sign_avb(orig_img_path, target_img_path, avbtool_bin):
    print(f"[*] Checking AVB footer on original image: {orig_img_path}")
    p = subprocess.run([avbtool_bin, "info_image", "--image", orig_img_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        print("[!] Original image is not AVB signed or has no footer. Skipping AVB signing.")
        return

    part_size = None
    fingerprint = None
    rollback_index = None
    rollback_index_location = None
    for line in p.stdout.splitlines():
        line_clean = line.strip()
        if "Image size:" in line:
            part_size = int(line.split(":")[-1].replace("bytes", "").strip())
        elif "com.android.build.vendor_boot.fingerprint" in line:
            fingerprint = line.split("->")[-1].strip().strip("'\"")
        elif line_clean.startswith("Rollback Index:") and "Location" not in line_clean:
            try:
                rollback_index = int(line_clean.split(":")[-1].strip())
            except ValueError:
                pass
        elif line_clean.startswith("Rollback Index Location:"):
            try:
                rollback_index_location = int(line_clean.split(":")[-1].strip())
            except ValueError:
                pass

    if part_size:
        print(f"[*] Re-signing with AVB hash footer (partition size: {part_size} bytes)...")
        sign_cmd = [
            avbtool_bin, "add_hash_footer",
            "--image", target_img_path,
            "--partition_size", str(part_size),
            "--partition_name", "vendor_boot",
        ]
        if fingerprint:
            sign_cmd.extend(["--prop", f"com.android.build.vendor_boot.fingerprint:{fingerprint}"])
        if rollback_index is not None:
            sign_cmd.extend(["--rollback_index", str(rollback_index)])
        if rollback_index_location is not None:
            sign_cmd.extend(["--rollback_index_location", str(rollback_index_location)])

        p_sign = subprocess.run(sign_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p_sign.returncode != 0:
            print(f"[!] AVB signing failed:\n{p_sign.stderr}")
        else:
            print(f"[+] AVB signature successfully written to {target_img_path}")

def main():
    parser = argparse.ArgumentParser(description="Universal GPU Overclock Patcher for Unisoc vendor_boot.img")
    parser.add_argument("input", help="Path to input vendor_boot.img")
    parser.add_argument("output", nargs="?", default=None, help="Path to output patched vendor_boot.img (optional)")
    parser.add_argument("-o", "--out", dest="out_flag", default=None, help="Output path (alternative)")
    parser.add_argument("--max-freq", type=int, default=1100, choices=[900, 1100, 1300, 1500, 1600],
                        help="Maximum active GPU frequency in MHz (default: 1100)")
    parser.add_argument("--all-freqs", action="store_true",
                        help="Populate all OPP levels up to 1600 MHz in OPP table, setting range-max to --max-freq")
    parser.add_argument("--work-dir", default="/tmp/vb_patch_work", help="Working directory for temporary files")
    parser.add_argument("--dtc", help="Custom path to dtc executable")
    parser.add_argument("--unpack-bootimg", help="Custom path to unpack_bootimg.py")
    parser.add_argument("--mkbootimg", help="Custom path to mkbootimg.py")
    parser.add_argument("--avbtool", help="Custom path to avbtool executable")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and display patch without writing output")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary unpack directory")

    args = parser.parse_args()

    input_img = os.path.abspath(args.input)
    if not os.path.isfile(input_img):
        sys.exit(f"[-] Input file not found: {input_img}")

    out_img = args.output or args.out_flag
    if not out_img:
        base, ext = os.path.splitext(input_img)
        out_img = f"{base}_oc_gpu_{args.max_freq}mhz{ext}"
    out_img = os.path.abspath(out_img)

    tools = detect_tools(args)
    work_dir = os.path.abspath(args.work_dir)

    print("="*60)
    print(" UNISOC VENDOR_BOOT GPU OVERCLOCK PATCHER")
    print("="*60)
    print(f" Input Image   : {input_img}")
    print(f" Output Image  : {out_img}")
    print(f" Target Max OC : {args.max_freq} MHz (1.{args.max_freq // 100 % 10} GHz)")
    print(f" Include All   : {args.all_freqs}")
    print("="*60)

    # 1. Unpack
    stdout_unpack = unpack_vendor_boot(input_img, work_dir, tools["unpack_bootimg"])
    info = parse_unpack_info(stdout_unpack)

    dtb_in = os.path.join(work_dir, "dtb")
    dts_out = os.path.join(work_dir, "kernel.dts")
    if not os.path.isfile(dtb_in):
        sys.exit("[-] dtb file not extracted by unpack_bootimg!")

    # 2. Decompile DTB -> DTS
    was_dtbo = decompile_dtb(dtb_in, dts_out, tools["dtc"])

    # 3. Build & Patch Table
    levels, max_idx = build_opp_table(args.max_freq, args.all_freqs)
    patch_dts_file(dts_out, levels, max_idx)

    if args.dry_run:
        print("[*] Dry run complete. No output image generated.")
        return

    # 4. Recompile DTS -> DTB
    compile_dtb(dts_out, dtb_in, tools["dtc"], was_dtbo)

    # 5. Repack vendor_boot
    repack_vendor_boot(work_dir, out_img, info, tools["mkbootimg"])

    # 6. Re-sign AVB
    sign_avb(input_img, out_img, tools["avbtool"])

    # 7. Cleanup
    if not args.keep_temp:
        shutil.rmtree(work_dir, ignore_errors=True)

    print("\n" + "="*60)
    print(f"[+] SUCCESS! Overclocked vendor_boot created:")
    print(f"    Path: {out_img}")
    print(f"    Size: {os.path.getsize(out_img):,} bytes")
    print(f"    Active Max Frequency: {args.max_freq} MHz")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
