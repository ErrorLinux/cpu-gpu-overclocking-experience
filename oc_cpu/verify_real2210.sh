#!/system/bin/sh
# verify_real2210.sh — Kiểm tra 2.21 GHz THỰC TẾ bằng ARM PMU
# Chạy sau khi flash sml_real2210mhz.img và reboot.

P=/sys/devices/system/cpu/cpufreq/policy6

echo "=== BANG DVFS (SML) ==="
cat /sys/kernel/debug/sprd-cpufreq-v2/cluster1/dvfs_table 2>/dev/null || echo "(khong doc duoc debugfs)"

echo ""
echo "=== TRANG THAI CPUBFREQ ==="
echo "policy6 min=$(cat $P/scaling_min_freq 2>/dev/null) max=$(cat $P/scaling_max_freq 2>/dev/null) cur=$(cat $P/scaling_cur_freq 2>/dev/null)"
echo "available: $(cat $P/scaling_available_frequencies 2>/dev/null)"

measure() {
  F=$1
  echo "$F" > "$P/scaling_max_freq" 2>/dev/null
  sleep 0.2
  taskset 40 sh -c 'while :; do :; done' &
  PID=$!
  sleep 0.1
  OUT=$(simpleperf stat -e cpu-cycles,task-clock -p "$PID" --duration 2 2>&1)
  kill "$PID" 2>/dev/null
  wait "$PID" 2>/dev/null
  CYC=$(echo "$OUT" | grep -E 'cpu-cycles' | head -1 | awk '{print $1}' | tr -d ',')
  TC=$(echo "$OUT" | grep -E 'task-clock' | head -1 | awk '{print $1}')
  echo "req=$F sysfs_cur=$(cat $P/scaling_cur_freq 2>/dev/null) cycles=$CYC task_clock_s=$TC"
}

echo ""
echo "=== DO PMU (taskset 40 = CPU6 A75) ==="
for F in 768000 1690000 2210000; do
  measure "$F"
done

echo ""
echo "Ket qua mong doi:"
echo "  768000  -> ~0.768 GHz"
echo "  1690000 -> ~1.690 GHz"
echo "  2210000 -> ~2.210 GHz (6.63e9 chu ky / 3s)"
