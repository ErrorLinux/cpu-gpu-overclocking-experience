// SPDX-License-Identifier: GPL-2.0
/*
 * sprd_cpu_oc - runtime CPU frequency control through SML SMC (serenity).
 *
 * SMC IDs recovered by disassembling stock sprd_sip_svc.ko:
 *   0x82000601 dvfs_enable(cluster, 0)
 *   0x82000602 table_update(cluster, temp, *out)
 *   0x82000603 step_set(cluster, index)
 *   0x82000604 margin_set(cluster, margin)
 *   0x82000605 freq_set(cluster, freq)     -> observed a0=-1 on this SML
 *   0x82000606 freq_get(cluster)           -> a1 = frequency in Hz (works)
 *   0x82000607 pair_get(cluster, index)    -> a1=Hz, a2=uV
 *   0x8200060b dvfs_init(cluster, a, b)
 */
#include <linux/init.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/arm-smccc.h>

#define SMC_DVFS_ENABLE       0x82000601UL
#define SMC_DVFS_STEP_SET     0x82000603UL
#define SMC_DVFS_FREQ_SET     0x82000605UL
#define SMC_DVFS_FREQ_GET     0x82000606UL
#define SMC_DVFS_PAIR_GET     0x82000607UL

static unsigned int oc_step_a55 = 7;
module_param(oc_step_a55, uint, 0644);
MODULE_PARM_DESC(oc_step_a55, "A55 OPP index to select (default 7 = top)");

static unsigned int oc_step_a75 = 6;
module_param(oc_step_a75, uint, 0644);
MODULE_PARM_DESC(oc_step_a75, "A75 OPP index to select (default 6 = top)");

static void probe_cluster(unsigned int cluster, unsigned int top_index)
{
	struct arm_smccc_res r;
	unsigned int i;

	/* read current frequency (Hz) */
	arm_smccc_smc(SMC_DVFS_FREQ_GET, cluster, 0, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_cpu_oc: clu%u freq_get = %u Hz (a0=%lu)\n",
		cluster, (unsigned int)r.a1, r.a0);

	/* read the OPP pairs 0..top_index (in range, safe) */
	for (i = 0; i <= top_index; i++) {
		arm_smccc_smc(SMC_DVFS_PAIR_GET, cluster, i, 0, 0, 0, 0, 0, &r);
		pr_info("sprd_cpu_oc: clu%u opp%u = %u Hz / %u uV (a0=%lu)\n",
			cluster, i, (unsigned int)r.a1, (unsigned int)r.a2, r.a0);
	}

	/* try step_set (the call the stock cpufreq driver uses) */
	arm_smccc_smc(SMC_DVFS_STEP_SET, cluster, top_index,
		      0, 0, 0, 0, 0, &r);
	pr_info("sprd_cpu_oc: clu%u step_set(%u) => a0=%lu\n",
		cluster, top_index, r.a0);

	/* try freq_set with Hz, for comparison */
	arm_smccc_smc(SMC_DVFS_FREQ_SET, cluster,
		      cluster == 0 ? 1820000000UL : 2210000000UL,
		      0, 0, 0, 0, 0, &r);
	pr_info("sprd_cpu_oc: clu%u freq_set(Hz) => a0=%lu\n", cluster, r.a0);

	arm_smccc_smc(SMC_DVFS_FREQ_GET, cluster, 0, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_cpu_oc: clu%u freq_get after = %u Hz (a0=%lu)\n",
		cluster, (unsigned int)r.a1, r.a0);
}

static int __init sprd_cpu_oc_init(void)
{
	pr_info("sprd_cpu_oc: diagnostic start\n");
	probe_cluster(0, oc_step_a55);
	probe_cluster(1, oc_step_a75);
	pr_info("sprd_cpu_oc: diagnostic done\n");
	return 0;
}

module_init(sprd_cpu_oc_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SML SMC diagnostics / CPU OC attempt (vendor_boot delivered)");
