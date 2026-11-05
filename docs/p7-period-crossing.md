# P7 跨周期机械联合验证

2026-11-06。承接[齿槽共能](p7-cogging-coenergy.md)，
固定判据见[先行契约](p7-period-crossing-contract.md)。

原机械示例的转角约0.038 rad，未跨过45°模型周期。本增量从0.1 rad、
±40 rad/s、零电流开始，以原20kHz PI和平均SVPWM运行50ms；
每方向分别使用5/2.5µs步长，要求至少跨两个模型周期。
机械角保留展开值，周期角只用于磁模型查询。
源能从零积分，储能账以初始磁能及动能为参考。原零初态接口和门槛保留。

## 复现和证据

```bash
python -m pip install -e ".[dev]" scipy
# 下载 snapshot-2026-11-05 release 的 open-engineering-report.zip 至 outputs/
python benchmarks/p7_cogging_extract.py
python benchmarks/p7_cogging_evaluate.py
python benchmarks/p7_cogging_simulation.py
python benchmarks/p7_period_crossing.py
```

四份完整CSV及summary.json保存到outputs/p7-cogging-report/period-crossing/。
汇总保存模型SHA、初态、拒绝原因、重放、细化和逐项判定；失败返回非零。
专用工作流在Python3.12/SciPy1.15.3上回归旧案例并归档新证据。

本地主机Windows/Python3.14、NumPy2.5.4、SciPy1.18.1：
297项测试通过、25项可选依赖/资产检查跳过，Ruff通过。
原三组零初态动态仿真及机械守恒极限通过。跳过不算后端通过，
本地主机结果与专用CI结果分别记录。

提交27e87fa的[专用远程运行](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/42065474433)
已通过；[完整证据包](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/42065474433/artifacts/13432838049)
保留原模型、原三组及四组跨周期轨迹。后续铜耗映射的CI结果按对应新提交另记。

四组跨周期仿真全部通过，正向行进2.54862周期、反向2.54820周期。
最大DOP853重放电流差3.40e-12 A，最大能量余额7.18e-13 J；
两步长闭环最大电流差2.20e-13 A、机械角差3.74e-14 rad、速度差1.13e-12 rad/s。
每组1000命令、1001端点，峰值电流L1为0.51284 A、峰值电压10.9161 V。
这些小误差说明同一冻结方程的数值一致性，不能解释为真实电机预测误差。

这是冻结模型的跨周期数值验证，没有新增FE、速度闭环或物理精度认证。
完整Gate B、独立场参照、同机型损耗到工程热场/ROM映射继续保留。
