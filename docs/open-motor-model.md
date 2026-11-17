# 外部磁链模型与开源联合实验

本入口调用 [motulator](https://github.com/Aalto-Electric-Drives/motulator) 的 SyR-e MAT 导入、饱和同步电机、PI电流/速度控制及 MTPA/MTPV 绘图；以 [Optuna](https://optuna.org/) 网格搜索两组速度环带宽。电机方程、积分器、控制器和搜索算法均由依赖库提供，项目只编排输入与结果。[实现前契约](open-motor-model-contract.md)。

```bash
python -m pip install motulator==0.25.0 optuna==4.5.0 'matplotlib>=3.10,<4'
MPLBACKEND=Agg python benchmarks/open_motor_lab.py --map /path/to/syre-model.mat --config benchmarks/assets/open-motor-thor.json --output outputs/open-motor-lab
```

配置仅为上游 THOR 示例，不可直接用于其他电机；要提供与实际模型匹配的极对数、电阻、转动惯量、母线电压、额定值和限制等。可用 SyR-e 结构的 MAT 文件直接输入；其它商业软件格式须先确认实际导出内容与坐标/单位约定，目前未实现自动转换。系统不会因格式相同而保证数据可信。

输出包含输入SHA、库版本、两轴磁链面、源转矩图、开源反向映射与源电流/转矩差异、控制轨迹、MTPA/MTPV相关图、两组带宽训练与负载留出结果，以及完整时域 NPZ。默认平均逆变器无死区/管压降，但有有限电压和一拍计算延迟。导入默认对称扩展负 q 轴；上游插值允许外推，报告只记录轨迹保存端点的逆表矩形越界，不能证明所有积分阶段都在有效域内。

此阶段没有足够的铁耗、角度谐波、温度和独立物理基准，不能提供可信完整效率图、转矩脉动或商业仿真软件等效精度；输出不得用于硬件保护定值。候选选择只针对示例的规定仿真指标，留出结果可能退化，均保留。
