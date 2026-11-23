// SPDX-License-Identifier: GPL-2.0
/* Read-only probe of the SML perf-clock SMC service (0x82000100).
 * Wrappers in sprd_sip_svc.ko:
 *   0x82000102 perf_get_freq(id, x)   -> a1
 *   0x82000104 perf_get_div(id)       -> a1
 *   0x82000106 perf_get_parent(id)    -> a1
 * Logs IDs that return a sensible non-zero value. */
#include <linux/init.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/arm-smccc.h>

#define SMC_GET_FREQ   0x82000102UL
#define SMC_GET_DIV    0x82000104UL
#define SMC_GET_PARENT 0x82000106UL

static int __init sprd_perf_probe_init(void)
{
	struct arm_smccc_res r;
	unsigned int id, svc;

	pr_info("sprd_perf_probe: start\n");
	for (svc = 0x100; svc <= 0x106; svc++) {
		for (id = 0; id <= 64; id++) {
			arm_smccc_smc(0x82000000UL | svc, id, 0, 0, 0, 0, 0, 0, &r);
			if (r.a0 != 0 || r.a1 != 0 || r.a2 != 0)
				pr_info("sprd_perf_probe: svc=%#x id=%2u a0=%lu a1=%lu a2=%lu\n",
					svc, id, r.a0, r.a1, r.a2);
		}
	}
	pr_info("sprd_perf_probe: done\n");
	return 0;
}
module_init(sprd_perf_probe_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Probe SML perf clock IDs");
