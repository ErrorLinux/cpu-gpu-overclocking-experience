// SPDX-License-Identifier: GPL-2.0
/*
 * sprd_dvfs_hw v6
 *   0x8200060B -> SML 0x5AD4: writes the runtime clamp tables 0xB00223D0/D8.
 *                a2 packs per cluster: bits[4:0]=max+1, bits[9:5]=min+1.
 *                max=10 for both clusters => a2 = 10 | (10<<10) = 0x280A.
 *   0x82000605 -> SML 0x58FC: freq_set(cluster, INDEX) -> 0x4B7C HW write.
 * No SMC in module_init.
 */
#include <linux/init.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/errno.h>
#include <linux/arm-smccc.h>

#define SMC_ENABLE   0x82000601UL
#define SMC_FREQ_SET 0x82000605UL
#define SMC_DVFS_INIT 0x8200060BUL

#define OC_CLUSTER 1  /* A75 */
static unsigned int oc_index;
static unsigned int oc_range;

static int set_range(const char *val, const struct kernel_param *kp)
{
	unsigned int v;
	struct arm_smccc_res r;
	int ret = kstrtouint(val, 0, &v);
	(void)kp;
	if (ret || v > 0xfffff)
		return -EINVAL;
	oc_range = v;
	arm_smccc_smc(SMC_DVFS_INIT, 0, v, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_dvfs_hw: DVFS_INIT range a2=%#x a0=%lu a1=%lu\n",
		v, r.a0, r.a1);
	return 0;
}
static int get_range(char *buf, const struct kernel_param *kp)
{
	(void)kp;
	return scnprintf(buf, PAGE_SIZE, "%u\n", oc_range);
}
static const struct kernel_param_ops range_ops = {
	.set = set_range, .get = get_range,
};
module_param_cb(oc_range, &range_ops, &oc_range, 0644);

static int set_index(const char *val, const struct kernel_param *kp)
{
	unsigned int idx;
	struct arm_smccc_res r;
	int ret = kstrtouint(val, 0, &idx);
	(void)kp;
	if (ret || idx > 9)
		return -EINVAL;
	oc_index = idx;
	/* mở clamp max=10 cho cả 2 cluster trước khi set index */
	arm_smccc_smc(SMC_DVFS_INIT, 0, 0x280A, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_dvfs_hw: DVFS_INIT clamp a0=%lu a1=%lu\n", r.a0, r.a1);
	arm_smccc_smc(SMC_ENABLE, OC_CLUSTER, 0, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_dvfs_hw: enable clu%u a0=%lu\n", OC_CLUSTER, r.a0);
	arm_smccc_smc(SMC_FREQ_SET, OC_CLUSTER, idx, 0, 0, 0, 0, 0, &r);
	pr_info("sprd_dvfs_hw: FREQ_SET clu%u idx%u a0=%lu a1=%lu a2=%lu\n",
		OC_CLUSTER, idx, r.a0, r.a1, r.a2);
	return 0;
}
static int get_index(char *buf, const struct kernel_param *kp)
{
	(void)kp;
	return scnprintf(buf, PAGE_SIZE, "%u\n", oc_index);
}
static const struct kernel_param_ops index_ops = {
	.set = set_index, .get = get_index,
};
module_param_cb(oc_index, &index_ops, &oc_index, 0644);

static int __init sprd_dvfs_hw_init(void)
{
	pr_info("sprd_dvfs_hw: v6 loaded; oc_range then oc_index\n");
	return 0;
}
module_init(sprd_dvfs_hw_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SML DVFS clamp unlock + index set");
