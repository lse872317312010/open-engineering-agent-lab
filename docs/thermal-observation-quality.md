# 无真值的六温度观测幅度检查

2026-10-29。针对PR #29恒温白噪声也产生满秩的反例。
本检查不修改拟合器、模型或原验收门槛，不把幅度足够解释为可辨识或可信。

固定规则：每通道计算经验P95-P05温度跨度，单位K。
调用方提供已知测量噪声标准差（非负标量或六向量）；不得用含动态的数据差分自动估计。
每通道跨度须严格大于max(6 sigma, 0.05K)。
6 sigma和0.05K是本研究的显式筛查策略，不是通用统计检验或物理精度保证。
Gaussian纯噪声总体P95-P05约3.2897 sigma，因此此基准应提示幅度不足；
独立均匀分位点解析案例验证跨度为90%的全宽，冻结测试后实现。

返回三态：insufficient（至少一通道不足）、unknown（未给噪声先验）、
amplitude_supported（全部超过门槛）。缺失/非有限数据直接拒绝；
噪声为零仍受绝对分辨幅度门槛约束。最少100个样本；
该最小数是适用策略，不代表独立有效样本数。

不使用参数真值、留出或功率，因此不能检测热源错误、常值温度偏置、
错误拓扑或参数误差。零功率但有温度变化的被动冷却可通过，不能简单按零输入拒绝。
返回每通道跨度、门槛、不足通道编号和噪声来源。噪声未知不默认零。
筛查为独立可选API，暂不自动阻断既有fit_network，保留历史失败重现实验。

验证：固定种子恒温噪声、多通道独立噪声尺度、无噪声常温、
被动冷却、常值偏移不变性、未知噪声、缺失传感器和无效输入。
运行ruff check .、专用pytest及原三版本unittest回归。
P7新增计划保持planned；本功能不是FE/ROM、稀疏观测或通用故障检测器。

## 使用与实际验证

```python
from oeal.thermal_observation import assess_temperature_observations
quality = assess_temperature_observations(temperatures_c, noise_sigma_k=0.02)
# temperatures_c: N×6，N>=100，单位°C；noise_sigma_k单位K。
# quality["status"]: unknown / insufficient / amplitude_supported
```

检查所有六通道，返回P95-P05跨度、逐通道门槛及不足通道编号。
此接口独立于fit_network，调用方自行展示诊断，既有拟合行为保持兼容。
目前未将该新诊断接入旧交互报告；旧报告的合成真值判据保持原义。

[专用工作流](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40906966646)
在提交`0e7b017b77fb6ad2662803f357fc0bcf14302f8c`上lint通过、9项pytest全部通过。
[三版本基础CI](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40906966643)成功；
基础CI运行unittest，不能把它当作pytest函数测试已执行。
首次验证另修复了tools/code_metrics.py继承的导入排序/未使用变量lint问题，
不改变代码统计行为。

这仍只是基于调用方噪声先验的幅度必要筛查，不是充分可辨识性证明。
后续应在完整20组MSL案例中联动展示幅度诊断与独立留出结果，再评测噪声建模。
