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

输出目录必须为空。证据校验失败时，命令在创建输出目录前退出。成功时保存时域数据、转速和转矩图、配置与模型哈希、磁图调用计数。模型构造或运行中若越界或发生其他错误，命令保存 `failure.json` 并退出。

专项 CI 使用上游 Baldor 预训练模型和公开数据，以宽松的合成预算运行 0.1 s 控制仿真，并验证超出预算的留出评估会阻止仿真。预训练模型可能使用过同一数据，该流程的证据范围为接口和拒绝路径。

当前仅支持用户明确确认的矩形域，矩形可能包含数据空洞：不应将训练点凸包或边界框自动视为物理有效域。预算和范围由用户提供，本程序不能验证其真实性或预算制定时机；摘要和哈希用于一致性与追溯，不提供签名认证。磁图接口的受保护调用可包含内部求解器阶段，但现阶段没有独立逐阶段审计，也没有负载变化、损耗、温度、算法优化、物理参考或最终留出数据独立性的认证。
