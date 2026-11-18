# 外部磁图的受限控制实验（实验性）

`benchmarks/p8_run_external_drive.py` 使用外部拟合入口生成的两张 GradNet 模型及 summary.json，校验模型哈希，并比较拟合验证集的磁链与电流 RMSE 和用户给定的预算。超过预算或哈希不匹配时拒绝运行。此验证集可能用于调参，并不替代独立最终留出或物理准确性验证。

驱动配置必须明确：

- `flux_domain_wb` 和 `current_domain_a`：分别为 [d最小值, d最大值, q最小值, q最大值]，必须覆盖模型构造和控制计算所需的调用，坐标及单位与源模型一致。
- `max_validation_flux_rmse_wb`、`max_validation_current_rmse_a`：用户按用途预先制定的正数误差预算。
- `resistance_ohm`、`inertia_kg_m2`、`dc_voltage_v`、`current_limit_a`、`speed_bandwidth_hz`、`duration_s`：明确来源的正数参数。
- `speed_reference_rad_s`：有限的机械角速度，可为正、零或负。当前命令固定在 0.01 s 后施加参考，使用上游在线磁链矢量控制、传感器与理想平均逆变器，不设置外部载荷。

```sh
python benchmarks/p8_run_external_drive.py --fit-dir outputs/fit --config drive.json --output outputs/drive
```

输出目录必须为空。成功时保存时域数据、转速和转矩图、配置与模型哈希、磁图调用计数；模型构造或运行中若越界或其他错误则保存 failure.json 并以失败退出，不裁剪或静默外推。

当前仅支持用户明确确认的矩形域，矩形可能包含数据空洞：不应将训练点凸包或边界框自动视为物理有效域。预算和范围由用户提供，本程序不能验证其真实性。磁图接口的受保护调用可包含内部求解器阶段，但现阶段没有独立逐阶段审计，也没有负载变化、损耗、温度、算法优化、物理参考或最终留出验收。
