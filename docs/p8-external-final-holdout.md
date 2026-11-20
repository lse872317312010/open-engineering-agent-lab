# 外部磁图最终留出评估（实验性）

拟合及参数选择完成后，使用从未参与训练和选择的独立留出 NPZ 执行一次评估。提供拟合目录、原训练和验证 NPZ、留出 NPZ 以及预先记录的 JSON 预算：

```json
{"flux_rmse_wb": 0.01, "flux_max_wb": 0.05,
 "current_rmse_a": 0.5, "current_max_a": 2.0}
```

上面数字只说明格式，实际门槛由用户根据电机、额定值和用途制定；程序不能证明门槛的制定时机。所有预算必须为有限正数。

```sh
python benchmarks/p8_evaluate_final_holdout.py --fit-dir outputs/fit \
  --train outputs/motor-splits/train.npz --validation outputs/motor-splits/validation.npz \
  --holdout outputs/motor-splits/holdout.npz --budget budget.json --output outputs/final
```

程序要求三组 NPZ 带有导入器来源清单，检查 model_id、极对数、dq 约定、温度与相序一致，并比对拟合摘要中的训练/验证数据和模型 SHA-256，检查三组之间电流和磁链输入是否完全重复或为 q 轴镜像，调用上游 motulator GradNet 模型求留出点误差。输出逐点预测、包含两幅子图的误差点图与含 SHA、RMSE、P95、最大误差和各项预算结果的 summary.json；若任一预算失败，结果仍保存，命令以失败状态退出。

`training_coverage` 分别在正向磁图的 dq 电流空间和反向磁图的 dq 磁链空间，用训练 NPZ 的原始点构建 SciPy 凸包。每个分组报告 GradNet 的点数、MAE、RMSE、P95、最大误差及按额定基值归一化的 RMSE。SciPy 线性插值与 GradNet 的对照只用凸包内、插值有限的同一批留出点；逐点 NPZ 保留每张磁图的覆盖标签、两种预测及基线缺值。训练输入共线时标记覆盖不可判定。重复输入对应不同目标时保留几何覆盖，线性基线标记不可用。

误差图按两张磁图各自的输入坐标显示，圈出超出训练凸包的点。凸包描述几何覆盖，内部仍可能有采样空洞。四项预算继续以全部留出点的 GradNet 误差为依据。

评估通过后，将 `summary.json`、原留出 NPZ 和预算 JSON 一起交给[受保护控制入口](p8-external-guarded-drive.md)。来源清单及其记录的哈希由数据提供方声明。精确检查针对完全重复和 q 轴镜像。数据独立性、物理来源、连续域精度和求解器阶段仍需各自的验证证据。
