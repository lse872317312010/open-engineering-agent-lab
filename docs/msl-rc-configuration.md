# MSL六节点热容与热阻配置

本轮新增固定资产OEALMSLParametric，不替换原OEALMSLCooling或原线性热FMU。
使用同版MSL实际HeatCapacitor/ThermalResistor/Convection/BodyRadiation；
由可信Python对象在FMI初始化前提供参数，不新增任意JSON模型路径。

| 参数 | 单位 | 默认 | 配置范围 |
| --- | --- | --- | --- |
| capacities_j_per_k | J/K | 60/70/200/0.5/25/100 | 六有限实数，各0.05..1000 |
| link_resistances_k_per_w | K/W | 0.6/0.4/2/0.8/1.2 | 五有限实数，各0.05..20 |
| case_resistance_k_per_w | K/W | 2 | 有限实数，0.05..20 |
| ambient_c | °C | 25 | −10..60 |
| initial_temperatures_c | °C | 六个80 | 六有限实数，各−10..120 |
| area（Gr） | m² | 调用方提供 | 0..0.1 |

六节点顺序：绕组、铁芯、壳体、结温、板、散热器。
五热阻依次连接：绕组—铁芯、铁芯—壳体、壳体—板、结温—板、板—散热器。
壳体到环境单独经Rcase；散热器到环境仍是对流和辐射并联。
对流Gc是外部等效W/K输入，Gr是合成有效面积，不代表风机转速或CFD。
表内范围是本项目合成研究输入的检查范围，不代表材料标定或器件额定值。

## 能量与状态机制

每节点使用C_i*dT_i/dt=实际热输入+相邻热流−边界热流。
内部热流为(T_a−T_b)/R_ab；节点对的两端等量反号，抵消后留下环境热流。
主机以实际C计算ΣC_i*(T_i−25°C)，并在能量余额中扣除真实初始储热。
三条散热积分和输入热累计与六温度、电磁和机械状态在同一求解器中积分。
增加热容会改变温度变化速度，也改变同一温差对应的储热；只改温度导数不足以通过能量验收。

提供方声明capacities_j_per_k，主机构造时复制为只读数组，
并核对ΣC_i*Tdot_i+Qambient−ΣPheat。
外部原数组被修改不会改变已经建立的主机账本；
若提供方随后返回与该C不符的导数，主机会拒绝该响应。
C/R均为初始化参数，本轮不支持积分中改变C、温度相关C/R或拓扑切换。
旧提供方不声明C时继续使用原默认算法，默认路径有逐位回归。

FMI根参数与从实际组件导出的12项参数观测值在初始化后核对：
六项node.C、五项path.R及case_path.R。六温度和四积分按XML派生的连续状态顺序映射，
每个接受点完成completedIntegratorStep后读取公开输出，保持求解器试探与接受状态的区别。

## 独立验证

[实现前契约](msl-rc-contract.md)冻结原输入和全部门槛。
零输入/无辐射情况下，由固定C/R图构造独立线性矩阵，并使用SciPy矩阵指数求解；
真实FMU采用主机DOP853积分。双热容在双时间应有相同温度轨迹和两倍散热积分。
另运行改变热阻的解析对照，以及实际电驱损耗、温度反馈、PWM和回馈；
全部RHS和所有控制点由独立端口方程重算。
参数化FMU的默认组合还与原固定MSL资产逐点配对。
独立Python热端口仍复用同一个上游电机；不是两个独立电机或实物验证。

## 复现与报告

固定库/编译器及基线检出命令见[专项工作流](../.github/workflows/msl-rc.yml)。

```bash
python benchmarks/build_msl_parametric.py
python benchmarks/build_msl_cooling.py
python benchmarks/validate_msl_rc_limits.py
python benchmarks/validate_msl_rc.py
python benchmarks/build_msl_rc_report.py
```

运行目录为outputs/msl-rc与outputs/msl-rc-report。
报告显示每组实际C、五R、Rcase、六初温/当前温度、实际电阻、源功及三条散热；
图表与验收读取完整控制轨迹，界面回放为抽样。
全部实际/参考CSV、原始RHS、故障副本、参数/模型/环境/二进制和文件散列另外归档。
本轮4–8秒是零输入解析极限，实际电驱为0.02–0.1秒参数化联合；
不能与之前1秒电驱或一小时热回放拼接为长时整机耐久。真机由用户负责。

报告显示修复可走工作流[report-only]模式：仅复用科学执行ee39dcd/40618818207，
逐一核对源/契约、全部保留文件manifest及Git差异允许清单，拒绝科学或依赖变更。
原始artifact失效或源/数据不符时需正常推送/手动workflow_dispatch进行完整科学运行。
