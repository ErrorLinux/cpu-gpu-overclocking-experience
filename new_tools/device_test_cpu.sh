#!/bin/sh
# device_test_cpu.sh — run on device after flashing a CPU margin image.
# Usage: adb push device_test_cpu.sh /data/local/tmp/ && adb shell "su -c 'sh /data/local/tmp/device_test_cpu.sh'"

OUT=/data/local/tmp/cpu_test_$(date +%Y%m%d_%H%M%S).log
echo "=== CPU margin test $(date) ===" > "$OUT"

echo "--- cpufreq tables ---" >> "$OUT"
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  echo "policy: $p" >> "$OUT"
  cat "$p/scaling_cur_freq" >> "$OUT" 2>/dev/null
  cat "$p/scaling_max_freq" >> "$OUT" 2>/dev/null
  cat "$p/scaling_min_freq" >> "$OUT" 2>/dev/null
done

echo "--- debugfs dvfs_table ---" >> "$OUT"
for f in /sys/kernel/debug/sprd-cpufreq/*/dvfs_table; do
  echo "cluster: $f" >> "$OUT"
  cat "$f" >> "$OUT" 2>/dev/null
done

echo "--- voltage readback ---" >> "$OUT"
for r in /sys/kernel/debug/regmap/*/registers; do
  case "$r" in *DCDC_CPU*|*dcdc_cpu*) echo "$r"; cat "$r" 2>/dev/null | head -5; esac
done >> "$OUT" 2>/dev/null

echo "--- thermal ---" >> "$OUT"
cat /sys/class/thermal/thermal_zone*/temp >> "$OUT" 2>/dev/null

echo "--- stress 300s ---" >> "$OUT"
# pin all cores to max
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  echo $(cat $p/scaling_max_freq) > $p/scaling_min_freq 2>/dev/null
  echo performance > $p/scaling_governor 2>/dev/null
done

# spawn sha256sum workers
for i in $(seq 0 7); do
  taskset -c $i sha256sum /dev/zero >/dev/null 2>&1 &
done

for i in $(seq 1 300); do
  echo "t=$i freq0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq) freq6=$(cat /sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq) temp=$(cat /sys/class/thermal/thermal_zone0/temp)" >> "$OUT"
  sleep 1
done

# cleanup
pkill -f sha256sum 2>/dev/null
echo "=== done ===" >> "$OUT"
echo "Log: $OUT"