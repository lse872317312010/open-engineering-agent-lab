# 六节点热参数合成辨识与数据隔离

采用已验收OEALMSLParametric真实MSL资产和SciPy1.15.3的lsq_linear，
辨识六热容、五内部热阻及壳体环境热阻。
[固定契约](msl-identification-contract.md) /
[方法与许可评审](../research/reviews/scipy-thermal-identification.md) /
[实际证据](stage-status.md)。

## 观察与辨识假设

六节点温度全部可观测，六热源功率已知且独立激励，
环境、Gc和Gr已知，拓扑和恒定参数结构匹配生成器。
数据是仿真内合成实验，不是实际电驱长时运行或实物标定。
传感器稀疏、未知源功、结构误差、温度相关参数和实测有效性继续待验证。

未知向量是C1..C6和G1..G5/Gcase（G=1/R）。
每个窗口使用C_i*ΔT_i及热流积分形成线性方程；
内部热流两端等量反号，已知散热器对流/辐射放在右侧。
温度用复合Simpson积分，源功用已知区间平均值积分；
不直接微分带噪温度。结温窗口0.5s，其他节点20s，采样0.05s。
按公开默认C归一化节点残差、再按列范数缩放；
检查12秩和条件数后，有界求解并转回R。
积分拟合残差包含观测噪声，区别于无噪声FMU的能量守恒误差。

## 分组与冻结

- train：1200s、25°C；24001个温度样本，各节点合成IID高斯噪声0.02K。
- validation：300s、25°C，新初温和源功时序。
- holdout：300s、60°C，新源功时序。

三组各有独立噪声种子及输入文件。
拟合CLI只打开train/measurements.csv与train/public.json；
纯函数fit_network只接收训练数组和已知边界，不接收真值/验证/留出。
设计矩阵保存在training-design.npz，训练包散列与实际优化诊断写入fitted.json。
参数文件冻结后，评估脚本再读取真值和未参与拟合的数据；
评估结束再次核对参数文件散列，禁止利用留出结果修改估计。

无噪声train轨迹的估计单独作为数学参考；
它不替代带噪估计，也不用于选择带噪参数。
标定预测在新FMU实例加载实际估计C/R，读取组件参数核对，
同时与独立Radau对照，将数值交换误差和参数预测误差分开。
公开默认参数基准、零激励拒绝及交换传感器列的故障均独立保留。

## 复现

沿用固定p6依赖、FMPy和编译镜像，命令/数据归档见
[工作流](../.github/workflows/msl-identification.yml)。

```bash
python benchmarks/build_msl_parametric.py
python benchmarks/generate_msl_identification.py
python benchmarks/fit_msl_identification.py
python benchmarks/validate_msl_identification.py
python benchmarks/build_msl_identification_report.py
```

结果位于outputs/msl-identification；报告位于outputs/msl-identification-report。
measurement.csv含温度观测及其后区间的平均/保持热源功率；
trajectory.csv和prediction.csv另含真实状态、输入及三支路积分。
报告展示参数估计、训练噪声、验证/留出预测、误差、可辨识性和能量，
并提供六节点状态回放、完整CSV及PDF/PNG/SVG。
原始包保留全部RHS、三个数据分组、真值、设计矩阵、故障副本、环境与散列。
真机由用户负责。
