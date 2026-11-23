#!/usr/bin/env bash
# Đo PMU tức thời KHÔNG đụng cpufreq (dùng sau khi ghi oc_index qua SMC 0x82000602).
# pmu_verify.sh sẽ set lại scaling_min/max -> cpufreq gọi SML -> ghi đè index ta vừa đặt.
set -e
adb shell su -c sh << 'SH_EOF'
echo "=== PLL lock / synth ==="
grep -E "^(0054|0088|0094):" /sys/kernel/debug/regmap/dummy-syscon@64580000/registers 2>/dev/null || true
echo "=== cpufreq hiện tại ==="
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq /sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq
echo "=== PMU A55 (cpu0) ==="
taskset 01 simpleperf stat -e cpu-cycles,task-clock -- timeout 0.5 sh -c 'while :; do :; done' 2>&1 | grep -E 'cpu-cycles|task-clock'
echo "=== PMU A75 (cpu6) ==="
taskset 40 simpleperf stat -e cpu-cycles,task-clock -- timeout 0.5 sh -c 'while :; do :; done' 2>&1 | grep -E 'cpu-cycles|task-clock'
SH_EOF
