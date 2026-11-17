# 开放磁图点表转换（P8-A，实验性）

将已经转换到 motulator 坐标约定的 CSV 点表存入 motulator-gradnet 可用的 NPZ；本步骤只保存数据，不运行磁图拟合或电机仿真。

CSV 必需列：id_A、iq_A、psi_d_Wb、psi_q_Wb。每行是同一工况的一个点，电流单位为峰值 A，磁链单位 Wb，复数约定为 d + j q。重复电流坐标和非有限数值会被拒绝。角度相关多组数据暂不支持；不要把不同转角或温度混在同一文件中。额外 CSV 列不进入 NPZ。

JSON 元数据必须包含 source_software、source_version、model_id、pole_pairs（正整数）、temperature_c（摄氏度）、dq_convention（固定为 motulator_peak_d_plus_jq）、phase_sequence、domain（源数据适用域说明）。坐标、相序和峰值约定须由导出方确认，工具不自动变换或推断。

```sh
python benchmarks/import_magnetic_points.py --csv motor.csv --metadata motor.json --output motor.npz
```

NPZ 包含上游使用的 i_s_dq、psi_s_dq 复数数组和 manifest_json（源 CSV/元数据 SHA-256、单位、元数据及点数）。须保留原始文件；NPZ 的点集不等于经过验证的插值有效域。输出尚未连接 open_motor_lab.py，原有联合仿真入口仍仅支持 SyR-e MAT。训练、误差留出、转矩图和效率图尚未实现。
