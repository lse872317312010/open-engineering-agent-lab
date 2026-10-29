# 辨识可靠边界：20组固定训练扰动

本轮在 PR #28 的全观测、已知热源合成辨识上增加敏感性与故障边界。
[实现前冻结契约](msl-identification-robustness-contract.md)与独立尺度歧义解析测试
先于实现提交：`8d9ad857385881af7af6a9a0cbd2408f8388997e`。
实际执行头 `9aa2a60ed114d1ff60fed51dc3b0643f9715c2d2`；
[专项工作流](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40834099841)成功。
证据等级为 `model_simulated`，没有实测标定。

## 结果与用途

全套试验 Gate 通过，20组中18组返回参数并完成300s留出预测，10组通过合成适用性门槛。
两个明确拒绝是缺失core温度与无噪声恒温零输入。
整套通过包含故障案例的预期失败，不是20组参数都可用。

| 温度白噪声 | 固定种子数 | 最大参数误差范围 | 最大节点留出RMSE范围 | 合成适用性 |
|---|---:|---:|---:|---|
| 0.02 K | 4 | 0.4672–0.7368% | 0.01944–0.02045 K | 4/4通过 |
| 0.10 K | 4 | 4.1517–5.6421% | 0.1799–0.2364 K | 4/4通过 |
| 0.50 K | 4 | 42.4634–52.8743% | 2.7070–4.0823 K | 0/4通过 |

- 功率记录全部减半：优化成功、rank12、无活动边界，但最大参数误差100.07%，
  留出最大节点RMSE12.9065 K、峰值19.8023 K。
- 恒温加0.02K噪声：rank12、condition1.6559，看似良态；返回的参数多项触边，
  留出最大节点RMSE839.059 K。这是退化数据上的非物理估计，不是可用模型。
- 绕组温度+2K：最大参数误差35.52%，不适用。
- 全部温度+2K：最大参数误差8.85%、最大节点RMSE0.3378K，仍通过本轮门槛。
  这表明本判据不能发现所有偏置，不能当作通用故障检测器。

相对误差为六C/五内部R/Rcase对合成真值；适用性同时要求无活动边界、
最大参数误差<=10%、每节点留出RMSE<=0.5K、峰值<=1.5K。
**真实数据没有这些真值，不能把该评价当作在线诊断。**
四个固定种子是有限重复，不是总体统计保证、置信区间或不确定度量化完成。
单组参数误差是12个物理参数的最大值，不是某一参数的误差分布。

## 数据边界与独立性

1. 重新导出固定真实MSL FMU，按原协议生成训练1200s、验证300s、留出300s。
2. 数据生成进程从干净训练轨迹构造20个包，逐个保存噪声种子/注入项与SHA256。
3. 独立拟合进程只打开包的训练CSV、公开边界及清单，不读取真值或验证/留出，
   不导入包含真值的生成协议。每个返回结果或异常写入独立JSON，再冻结SHA256。
4. 评价器随后读取合成真值及实际MSL留出轨迹，以原独立分段Radau方程预测所有18个成功拟合。
   不先筛掉参数误差大的结果；每组均保留6001行预测/真值/热源CSV。
5. 再校验所有拟合文件冻结哈希。无噪声预测另以DOP853对照，
   峰值温度差`1.9831674080705852e-9 K`，门槛2e-6K。
   本轮逐组预测是独立方程，不声称18组均加载了新FMU。
   原基准的新FMU预测/独立能量门槛在同一工作流重新执行并通过。

绝热网络中(C,G,P)同比缩放不改变温度导数，独立解析基准说明未知源尺度的歧义；
实际实验的已知对流/辐射边界仍保留，没有将该极限套作所有边界下的定理。
恒温两个包是故意生成的退化案例，不是MSL实际激励轨迹。
缺失温度被拒绝，没有插值或实现稀疏观测估计。

## 逐组结果

| 案例 | 求解器 | 合成适用性 | 最大参数相对误差 | 最大节点RMSE / K |
|---|---|---|---:|---:|
| ideal | 成功 | 通过 | 0.0000% | 6.6044e-8 |
| noise-0.02-1 | 成功 | 通过 | 0.4672% | 0.019464 |
| noise-0.02-2 | 成功 | 通过 | 0.7368% | 0.019443 |
| noise-0.02-3 | 成功 | 通过 | 0.6226% | 0.020445 |
| noise-0.02-4 | 成功 | 通过 | 0.4969% | 0.019551 |
| noise-0.10-1 | 成功 | 通过 | 4.1517% | 0.17993 |
| noise-0.10-2 | 成功 | 通过 | 4.9246% | 0.23640 |
| noise-0.10-3 | 成功 | 通过 | 5.6421% | 0.20892 |
| noise-0.10-4 | 成功 | 通过 | 4.7701% | 0.22011 |
| noise-0.50-1 | 成功 | 不通过/未评价 | 42.4634% | 2.7070 |
| noise-0.50-2 | 成功 | 不通过/未评价 | 52.8743% | 4.0823 |
| noise-0.50-3 | 成功 | 不通过/未评价 | 48.3201% | 3.0207 |
| noise-0.50-4 | 成功 | 不通过/未评价 | 47.3022% | 3.1787 |
| winding-bias | 成功 | 不通过/未评价 | 35.5179% | 0.69986 |
| common-bias | 成功 | 通过 | 8.8489% | 0.33775 |
| power-half | 成功 | 不通过/未评价 | 100.0667% | 12.907 |
| winding-power-zero | 成功 | 不通过/未评价 | 1222.7872% | 124.07 |
| missing-core | 拒绝 | 不通过/未评价 | — | — |
| equilibrium | 拒绝 | 不通过/未评价 | — | — |
| equilibrium-noisy | 成功 | 不通过/未评价 | 3900.0000% | 839.06 |

## 报告与复现

[下载四图交互报告，15.6MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40834099841/artifacts/12880012724) /
[完整原始证据，166.5MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40834099841/artifacts/12880027697)。
链接指向GitHub稳定artifact页面，需登录有权限的GitHub账号；不使用临时签名链接。
解压打开`index.html`，不需要服务器。20案例选择器、求解/适用性分别显示，
十二参数表、六节点温度、20项热容/热源/内热流/环境散热机制卡片及误差曲线。
拒绝案例隐藏预测，完整失败原因保留。
四图PDF/PNG/SVG、逐组拟合JSON、全量预测CSV与汇总CSV同时提供。

Chrome156.0.8078.47实际验证20案例、18组CSV下载/6001行、时间键盘端点、播放暂停、
拒绝状态、390px布局、图像/PDF；页面错误与外部请求为空。
lint通过；pytest **138通过、8跳过、14警告**，跳过项不算作通过。
MSL/求解器/许可证复用前一轮固定版本；环境和全输出SHA256在原始包。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python -m pip install "motulator @ git+https://github.com/Aalto-Electric-Drives/motulator.git@2ffbf1ae52d5fadcdffd85d10c80dd15fd2e39fa"
ruff check .
python -m pytest
python benchmarks/build_msl_parametric.py
python benchmarks/generate_msl_identification.py
python benchmarks/fit_msl_identification.py
python benchmarks/validate_msl_identification.py
python benchmarks/generate_msl_identification_robustness.py
python benchmarks/fit_msl_identification_robustness.py
python benchmarks/validate_msl_identification_robustness.py
python benchmarks/build_msl_identification_robustness_report.py
```

完整工具链与浏览器环境见[工作流](../.github/workflows/msl-identification-robustness.yml)。
下一步应先改进无真值条件下的激励/观测质量判别与噪声模型，再推进稀疏观测、
未知源、结构误差和温度依赖；本轮只是暴露这些边界，不宣称已经解决。
长时实际电驱、传动参数、整机/事件交换与完整FOC内核继续保留。
