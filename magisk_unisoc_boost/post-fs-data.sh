#!/system/bin/sh
# Early boot initialization for Unisoc Turbo Boost
# Runs in post-fs-data mode

# Disable thermal daemon early if possible
setprop vendor.thermal.enable 0
setprop persist.vendor.thermal.engine 0
