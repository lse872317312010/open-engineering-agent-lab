# 外部磁图训练入口（实验性）

先按[点表导入说明](p8-open-point-import.md)准备已明确 dq 约定的 NPZ，再由数据提供方按电流和角度区域生成独立训练与验证 NPZ。两个文件均包含 i_s_dq 和 psi_s_dq 复数数组（峰值 A、Wb）。本入口使用上游 motulator-gradnet 训练磁链图和电流图，验证数据只作诊断；最终留出数据须单独保管，不用于调参。

也可在原始 CSV 中增加 split 列，逐行填写 train、validation 或 holdout，三组各至少四点，再使用：

```sh
python benchmarks/p8_split_points.py --csv motor-labeled.csv --metadata motor.json --output outputs/motor-splits
```

它按用户标签生成各组 CSV/NPZ、源 CSV 记录序号映射（标题为第 1 条）和哈希清单，拒绝跨组完全相同或 q 轴共轭的电流及磁链输入。检查不覆盖数值近似、测量相关性或相邻点泄漏；有效域和分组必须由用户按来源数据确定。输出 holdout.npz 单独封存，不提供给拟合命令。CSV 若包含 torque_Nm，元数据必须明确 torque_convention 为 electromagnetic_total_Nm；源转矩将按同一行对应关系存入各组 NPZ，不做极对数或符号换算。训练入口暂不把转矩用于拟合。

依赖 Python 3.12+，motulator 0.25.0，以及固定上游提交 940d3b2daf3abd3ecca157f93cf4cc5363f5bb80 的 motulator-gradnet；训练使用 CPU 和上游固定种子 42。提供 JSON 名义配置，值必须与源电机一致：

```json
{"pole_pairs": 2, "voltage_v": 460, "current_a": 8.8,
 "frequency_hz": 60, "power_w": 5600, "torque_nm": 29.7}
```

上述值仅来自公开 Baldor 示例，不能套用到其他电机。电压、电流与频率遵循 motulator NominalValues 的额定输入约定；源温度、相序、有效域和其他设备限制由用户记录。

```sh
python benchmarks/p8_fit_external.py --train train.npz --validation validation.npz \
  --nominal nominal.json --output outputs/fit --epochs 2000
```

输出目录必须为空。生成两张上游模型 NPZ、验证点预测数据、d/q 分量验证图、上游磁图雅可比的四分量增量电感点图与 summary.json，记录输入、模型 SHA-256、库版本、基值及训练/验证误差。验证图只显示原始验证点，不将空白区域视为有效磁图。程序拒绝两组数据中完全相同或 q 轴共轭的电流与磁链输入；该检查不能检测近似重复点、相邻点泄漏或物理数据错误。用户需维护可信的空间分区和独立最终留出。

该命令不执行角度谐波、转矩/损耗、完整效率、有效域保护、控制联合仿真或物理误差验收。错误较大、来源不明或缺乏有效域的数据不能用于声称可信模型。

增量电感由上游 GradNet 磁链映射的雅可比给出，仅在提供的验证点计算，单位 H；不等同于与有限元差分电感或物理测量的独立验证。源数据缺少可用参考时不宣称电感精度。

训练结果还可生成离线交互验证点报告（需安装 plotly 6.3.0）：

```sh
python benchmarks/p8_map_dashboard.py --fit-dir outputs/fit --output outputs/map-report.html
```

HTML 内嵌 Plotly 脚本，支持切换磁链/电流及 d/q 分量、缩放和悬停，显示验证 RMSE 与源/预测/误差。报告只显示输入验证点，不将点外区域或物理有效域涂成可信曲面；旁车 JSON 保存输入和输出哈希。训练结果、数据、最终留出与来源声明需另行保存。
