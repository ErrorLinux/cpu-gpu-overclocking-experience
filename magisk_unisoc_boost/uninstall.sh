#!/system/bin/sh
# Cleanup upon module removal
# Restore read-write access to sysfs nodes
for pol in /sys/devices/system/cpu/cpufreq/policy*; do
    [ -d "$pol" ] || continue
    chmod 644 "$pol/scaling_max_freq" 2>/dev/null
    chmod 644 "$pol/scaling_min_freq" 2>/dev/null
    chmod 644 "$pol/scaling_governor" 2>/dev/null
done
for cdev in /sys/class/thermal/cooling_device*/cur_state; do
    [ -f "$cdev" ] && chmod 644 "$cdev" 2>/dev/null
done
rm -f /data/local/tmp/unisoc_turbo_boost.log
start vendor.thermald 2>/dev/null
