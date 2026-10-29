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
PR #36已将该诊断接入20组实验与交互报告；合成真值判据保持原义。

[专用工作流](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40906966646)
在提交`0e7b017b77fb6ad2662803f357fc0bcf14302f8c`上lint通过、9项pytest全部通过。
[三版本基础CI](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40906966643)成功；
基础CI运行unittest，不能把它当作pytest函数测试已执行。
首次验证另修复了tools/code_metrics.py继承的导入排序/未使用变量lint问题，
不改变代码统计行为。

这仍只是基于调用方噪声先验的幅度必要筛查，不是充分可辨识性证明。
后续应在完整20组MSL案例中联动展示幅度诊断与独立留出结果，再评测噪声建模。

## 2026-10-30：接入20组MSL实验与交互报告（PR #36）

训练进程使用训练温度与public.json的噪声先验计算quality；
有效记录同时检查移除噪声先验后返回unknown。缺失温度记invalid。
诊断与拟合JSON共同冻结SHA256，评价器只传递结果；
不阻断原拟合、不筛掉失败预测，不改变原20组固定门槛。

[专项运行40908576468](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40908576468)
在`8349f2e070434a3c4718b89273645e9b0f50cc52`成功；lint和pytest147通过、8跳过、14警告。
重新生成实际MSL数据，原新FMU参数/预测/能量基准和独立Radau留出检查均通过。
20组中17组amplitude_supported、2组insufficient、1组invalid；
两种恒温均幅度不足，缺失core无效，19个有效记录移除先验后均unknown。
18组仍返回拟合，10组通过原合成适用性门槛。
17组幅度支持中仍有7组不适用，说明该诊断不是充分可信性判据。

[新版五图报告，15.8MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40908576468/artifacts/12912184941) /
[完整原始证据，166.6MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40908576468/artifacts/12912738628)。
解压打开index.html。分别显示训练观测、优化器和合成适用性；
逐案例六行跨度/门槛/不足标记，无效记录显示原因；新增幅度/门槛与留出RMSE图。
报告仍提供六节点运行机制、20项热源/热流卡、完整CSV、冻结JSON、PDF/PNG/SVG。
Chrome156.0.8078.47检查全部20案例质量状态和表格、18组完整CSV下载、
回放端点/播放暂停、390px布局；页面错误和外部请求为空。
新版summary.csv增加观测状态和噪声来源。
适用范围model_simulated；噪声先验为公开合成训练配置，不是从含动态测量中自动估计。
P7仍按新增路线图推进，本次接入不代表已实现FE或ROM。
