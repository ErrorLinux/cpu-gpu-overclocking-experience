#!/usr/bin/env bash
# Script đo kiểm chu kỳ phần cứng ARM PMU đồng thời cho cả:
# 1. Cortex-A55 (Nhân nhỏ cpu0-5, policy0)
# 2. Cortex-A75 (Nhân to cpu6-7, policy6)
# Chạy an toàn từ máy host (Linux) qua ADB.

set -e

DEVICE=$(adb devices | grep -w "device" | head -n 1 | awk '{print $1}')
if [ -z "$DEVICE" ]; then
    echo "ERROR: Không tìm thấy thiết bị ADB online!"
    exit 1
fi

echo "=================================================================="
echo "    BỘ ĐO KIỂM PMU CHU KỲ PHẦN CỨNG CPU DUAL-CLUSTER (UMS9230E)   "
echo "=================================================================="
echo "Thiết bị kết nối: $DEVICE"
echo ""

adb shell su -c sh << 'SH_EOF'
echo "======================================================"
echo "1. TRẠNG THÁI KHÓA PLL & SYNTHESIZER (0x64580000)"
echo "======================================================"
if [ -f /sys/kernel/debug/regmap/dummy-syscon@64580000/registers ]; then
    REGS=$(grep -E "^(0054|0080|0084|0088|008c|0090|0094):" /sys/kernel/debug/regmap/dummy-syscon@64580000/registers 2>/dev/null || true)
    REG_54=$(echo "$REGS" | grep "^0054:" | awk '{print $2}')
    REG_80=$(echo "$REGS" | grep "^0080:" | awk '{print $2}')
    REG_84=$(echo "$REGS" | grep "^0084:" | awk '{print $2}')
    REG_88=$(echo "$REGS" | grep "^0088:" | awk '{print $2}')
    REG_8C=$(echo "$REGS" | grep "^008c:" | awk '{print $2}')
    REG_90=$(echo "$REGS" | grep "^0090:" | awk '{print $2}')
    REG_94=$(echo "$REGS" | grep "^0094:" | awk '{print $2}')
    echo "Reg 0x0054 (PLL Lock Status)       : $REG_54"
    echo "Reg 0x0080 (Channel 2 - 1612 MHz)  : $REG_80"
    echo "Reg 0x0084 (Channel 3 - 1690 MHz)  : $REG_84"
    echo "Reg 0x0088 (Channel 4 - A75 Max)   : $REG_88"
    echo "Reg 0x008c (Channel 5 - 1898 MHz)  : $REG_8C"
    echo "Reg 0x0090 (Channel 6 - 1950 MHz)  : $REG_90"
    echo "Reg 0x0094 (Channel 7 - 2210 MHz)  : $REG_94"
    if echo "$REG_54" | grep -q "^0002"; then
        echo "=> MPLL1: ĐÃ KHÓA THÀNH CÔNG (Bit 17 = 1, HOẠT ĐỘNG HOÀN HẢO!)"
    else
        echo "=> MPLL1: MẤT KHÓA (Bit 17 = 0, đang bypass thạch anh 26 MHz!)"
    fi
fi
echo ""

echo "======================================================"
echo "2. QUÉT & ĐO CHU KỲ VẬT LÝ ARM PMU - CORTEX-A55 (CPU0)"
echo "======================================================"
AVAIL0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_available_frequencies)
echo "Danh sách tần số khả dụng (policy0): $AVAIL0"
OLD_MIN0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq)
OLD_MAX0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq)

for f in $AVAIL0; do
    echo "$f" > /sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq
    echo "$f" > /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq
    sleep 0.1
    cur=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq)
    
    PERF=$(taskset 01 simpleperf stat -e cpu-cycles,task-clock -- timeout 0.4 sh -c "while :; do :; done" 2>&1)
    CYCLES=$(echo "$PERF" | grep "cpu-cycles" | awk '{print $1}' | tr -d ',')
    TASK_MS=$(echo "$PERF" | grep "task-clock" | awk '{print $1}' | sed 's/(ms)//g' | tr -d ',')
    
    if [ -n "$CYCLES" ] && [ -n "$TASK_MS" ]; then
        GHZ=$(awk -v c="$CYCLES" -v t="$TASK_MS" 'BEGIN { printf "%.3f", (c / (t * 1000000)) }')
        echo "Target: ${f} kHz | Cur: ${cur} kHz | Cycles: ${CYCLES} in ${TASK_MS}ms => PMU: ${GHZ} GHz"
    else
        echo "Target: ${f} kHz | Cur: ${cur} kHz | Error measuring PMU"
    fi
done

echo "$OLD_MIN0" > /sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq
echo "$OLD_MAX0" > /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq
echo "Đã khôi phục giới hạn policy0."
echo ""

echo "======================================================"
echo "3. QUÉT & ĐO CHU KỲ VẬT LÝ ARM PMU - CORTEX-A75 (CPU6)"
echo "======================================================"
AVAIL6=$(cat /sys/devices/system/cpu/cpufreq/policy6/scaling_available_frequencies)
echo "Danh sách tần số khả dụng (policy6): $AVAIL6"
OLD_MIN6=$(cat /sys/devices/system/cpu/cpufreq/policy6/scaling_min_freq)
OLD_MAX6=$(cat /sys/devices/system/cpu/cpufreq/policy6/scaling_max_freq)

for f in $AVAIL6; do
    echo "$f" > /sys/devices/system/cpu/cpufreq/policy6/scaling_min_freq
    echo "$f" > /sys/devices/system/cpu/cpufreq/policy6/scaling_max_freq
    sleep 0.1
    cur=$(cat /sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq)
    
    PERF=$(taskset 40 simpleperf stat -e cpu-cycles,task-clock -- timeout 0.4 sh -c "while :; do :; done" 2>&1)
    CYCLES=$(echo "$PERF" | grep "cpu-cycles" | awk '{print $1}' | tr -d ',')
    TASK_MS=$(echo "$PERF" | grep "task-clock" | awk '{print $1}' | sed 's/(ms)//g' | tr -d ',')
    
    if [ -n "$CYCLES" ] && [ -n "$TASK_MS" ]; then
        GHZ=$(awk -v c="$CYCLES" -v t="$TASK_MS" 'BEGIN { printf "%.3f", (c / (t * 1000000)) }')
        echo "Target: ${f} kHz | Cur: ${cur} kHz | Cycles: ${CYCLES} in ${TASK_MS}ms => PMU: ${GHZ} GHz"
    else
        echo "Target: ${f} kHz | Cur: ${cur} kHz | Error measuring PMU"
    fi
done

echo "$OLD_MIN6" > /sys/devices/system/cpu/cpufreq/policy6/scaling_min_freq
echo "$OLD_MAX6" > /sys/devices/system/cpu/cpufreq/policy6/scaling_max_freq
echo "Đã khôi phục giới hạn policy6."
SH_EOF
