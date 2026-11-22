#!/bin/bash
# stress_test_cpu.sh — Push to device and run stress test for CPU OC verification
# Usage: ./stress_test_cpu.sh [duration_seconds]
# Default: 120 seconds

DURATION="${1:-120}"

echo "=== Pushing stress test script to device ==="
adb push /home/hoang/Downloads/oc_gpu/new_tools/device_test_cpu.sh /data/local/tmp/

echo "=== Running stress test (${DURATION}s) ==="
echo "=== Monitor output ==="

adb shell "su -c 'sh /data/local/tmp/device_test_cpu.sh'" &
TEST_PID=$!

# Live monitor while test runs
echo ""
echo "--- Live frequency/temp monitor ---"
for i in $(seq 1 $DURATION); do
    freq0=$(adb shell "cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq" 2>/dev/null | tr -d '\r')
    freq6=$(adb shell "cat /sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq" 2>/dev/null | tr -d '\r')
    temp=$(adb shell "cat /sys/class/thermal/thermal_zone0/temp" 2>/dev/null | tr -d '\r')
    printf "t=%3d  A55=%7s kHz  A75=%7s kHz  Temp=%s\n" "$i" "$freq0" "$freq6" "$temp"
    sleep 1
done

wait $TEST_PID 2>/dev/null
echo ""
echo "=== Pulling log from device ==="
adb pull /data/local/tmp/cpu_test_*.log . 2>/dev/null
echo "=== Done ==="
