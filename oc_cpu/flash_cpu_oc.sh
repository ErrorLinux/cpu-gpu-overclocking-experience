#!/bin/bash
# flash_cpu_oc.sh — Flash CPU overclock image (SML magic64) to Redmi A5 (serenity)
# Target: A75 2.210 GHz @ 1050 mV (stock: 1.818 GHz @ 909 mV)
#
# PREREQUISITES:
#   - Device in BDL download mode (hold Volume Down while plugging USB)
#   - spd_dump installed and in PATH
#   - fdl1-dl.bin and fdl2-dl.bin in current directory (from spreadtrum_flash)
#
# USAGE:
#   ./flash_cpu_oc.sh                     # flash OC image
#   ./flash_cpu_oc.sh --restore           # flash stock image
#   ./flash_cpu_oc.sh --verify            # verify after boot (via ADB)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OC_IMAGE="$SCRIPT_DIR/sml_cpu_oc_2210mhz_1050mv.img"
STOCK_IMAGE="$SCRIPT_DIR/serenity_global_images_A17.0.4.0.XGWMIXM_17.0/images/sml-sign.bin"

# Adjust these paths if your fdl binaries are elsewhere
FDL1="${FDL1:-fdl1-dl.bin}"
FDL2="${FDL2:-fdl2-dl.bin}"

flash_image() {
    local img="$1"
    local label="$2"
    echo "=== Flashing $label ==="
    echo "  Image: $img"
    echo "  Size:  $(stat -c%s "$img") bytes"
    echo "  SHA256: $(sha256sum "$img" | cut -d' ' -f1)"
    echo ""
    echo "Running spd_dump..."
    spd_dump exec_addr 0x65015f08 \
        fdl "$FDL1" 0x65000800 \
        fdl "$FDL2" 0x9efffe00 \
        exec \
        w sml_a "$img" \
        w sml_b "$img" \
        reset
    echo ""
    echo "=== Done! Device will reboot. ==="
}

verify_oc() {
    echo "=== Verifying CPU overclock via ADB ==="
    echo ""
    echo "--- Max frequencies ---"
    adb shell "cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq"
    echo ""
    echo "--- Available frequencies (A55 cluster) ---"
    adb shell "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies"
    echo ""
    echo "--- Available frequencies (A75 cluster) ---"
    adb shell "cat /sys/devices/system/cpu/cpu6/cpufreq/scaling_available_frequencies"
    echo ""
    echo "--- Current frequencies ---"
    adb shell "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"
    echo ""
    echo "--- DVFS tables (debugfs) ---"
    adb shell "su -c 'cat /sys/kernel/debug/sprd-cpufreq/*/dvfs_table'" 2>/dev/null || echo "(debugfs not available or no root)"
    echo ""

    # Check if OC applied
    max_a75=$(adb shell "cat /sys/devices/system/cpu/cpu6/cpufreq/cpuinfo_max_freq" | tr -d '\r')
    if [ "$max_a75" = "2210000" ]; then
        echo "✅ SUCCESS: A75 max frequency = 2210000 kHz (2.21 GHz)"
    else
        echo "❌ FAILED: A75 max frequency = $max_a75 kHz (expected 2210000)"
    fi

    max_a55=$(adb shell "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq" | tr -d '\r')
    if [ "$max_a55" = "1820000" ]; then
        echo "✅ SUCCESS: A55 max frequency = 1820000 kHz (1.82 GHz)"
    else
        echo "⚠️  A55 max frequency = $max_a55 kHz (expected 1820000)"
    fi
}

case "${1:-}" in
    --restore)
        if [ ! -f "$STOCK_IMAGE" ]; then
            echo "ERROR: Stock image not found: $STOCK_IMAGE"
            exit 1
        fi
        flash_image "$STOCK_IMAGE" "STOCK (restore)"
        ;;
    --verify)
        verify_oc
        ;;
    *)
        if [ ! -f "$OC_IMAGE" ]; then
            echo "ERROR: OC image not found: $OC_IMAGE"
            exit 1
        fi
        echo "╔══════════════════════════════════════════════════╗"
        echo "║  CPU Overclock: A75 1.818 GHz → 2.210 GHz      ║"
        echo "║  Voltage:       909 mV → 1050 mV               ║"
        echo "║  Also: A55 1.612 GHz → 1.820 GHz               ║"
        echo "╚══════════════════════════════════════════════════╝"
        echo ""
        read -p "Continue? (y/N) " confirm
        if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
            echo "Aborted."
            exit 0
        fi
        flash_image "$OC_IMAGE" "CPU OC (2.21 GHz / 1050 mV)"
        echo ""
        echo "After device boots, run:  $0 --verify"
        ;;
esac
