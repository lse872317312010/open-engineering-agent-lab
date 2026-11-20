# 外部磁图的受限控制实验（实验性）

`benchmarks/p8_run_external_drive.py` 使用外部拟合入口生成的两张 GradNet 模型及 `summary.json`，校验模型哈希，并将拟合验证集的磁链与电流 RMSE 与各自预算比较。运行前还需用[最终留出评估](p8-external-final-holdout.md)生成通过的摘要。驱动入口核对留出 NPZ、预算、拟合摘要和模型的哈希，从 NPZ 核对来源清单与点数，并检查摘要记录的磁链和电流 RMSE、最大误差是否满足四项预算。

驱动配置必须明确：

- `flux_domain_wb` 和 `current_domain_a`：分别为 [d最小值, d最大值, q最小值, q最大值]，必须覆盖模型构造和控制计算所需的调用，坐标及单位与源模型一致。
- `max_validation_flux_rmse_wb`、`max_validation_current_rmse_a`：用户按用途预先制定的正数误差预算。
- `resistance_ohm`、`inertia_kg_m2`、`dc_voltage_v`、`current_limit_a`、`speed_bandwidth_hz`、`duration_s`：明确来源的正数参数。
- `speed_reference_rad_s`：有限的机械角速度，可为正、零或负。当前命令固定在 0.01 s 后施加参考，使用上游在线磁链矢量控制、传感器与理想平均逆变器，不设置外部载荷。

```sh
python benchmarks/p8_run_external_drive.py --fit-dir outputs/fit --config drive.json \
  --holdout outputs/motor-splits/holdout.npz --holdout-budget budget.json \
  --final-evidence outputs/final/summary.json --output outputs/drive
```

输出目录必须为空。证据校验失败时，命令在创建输出目录前退出。成功时保存时域数据、转速和转矩图、配置与模型哈希、磁图调用计数。`trajectory.npz` 还包含保存时刻的转子 dq 磁链 `flux_dq_wb`。

### 积分器磁链审计

`solver-flux-audit.npz` 按调用顺序记录 motulator 每次计算状态导数时的时间（s）、转子 dq 磁链（Wb）以及当前次调用内反向磁图的执行和拒绝次数。记录包含 RK45 内部阶段，时间可重复或回退。审计独立对照声明的闭区间，要求每个域内点恰好执行一次磁图，每个越界点由保护拒绝且没有执行磁图。成功摘要保存审计文件哈希、计数和求解器配置。模型构造或运行失败时，`failure.json` 保存对应的审计摘要和已记录的数据，并标出首次越界的调用索引（从 0 起）。

[专项工作流](../.github/workflows/p8-external-drive.yml)使用上游 Baldor 预训练模型和公开数据验证三条路径。宽合成域下完成 0.1 s 仿真。固定 `|ψq| ≤ 0.01 Wb` 的合成反例在 RK45 内部阶段拒绝，保留失败记录。最终留出误差超限时，仿真在创建输出目录前拒绝启动。

审计覆盖求解器实际请求的反向磁图输入与事先声明的矩形范围。控制器和雅可比调用仍经过各自的磁图保护。矩形可能包含数据空洞，积分阶段之间的连续轨迹和物理有效域需要各自的验证证据。公开样本可能参与过预训练，专项结果仅用于接口验证。
