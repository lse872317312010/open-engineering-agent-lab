# Open Engineering Agent Lab

在同几何定子热场上继续加入[边界敏感性与22状态ROM](docs/p7-stator-rom.md)：
训练冻结后用未参与拟合的边界/波形验证，提供NumPy-only 400Hz热更新及实际主机计时。
其范围是固定合成材料和均匀槽绕组热源回放，完整热精度与控制反馈链仍待验收。

同机型铜耗已继续接入[二维定子瞬态热场](docs/p7-stator-thermal.md)：
公开槽绕组几何、共形网格、合成热材料、源/储能/散热账及可复现全场产物。
范围为单向热源回放；完整工程热精度和同几何ROM闭环仍待验收。

面向 PMSM / FOC / 机器人关节研究的 Python + Agent 工程实验仓库。
参数和工况使用开放 JSON，仿真输出 CSV/JSON，验收与提议策略分离。

项目总图、运行机制与源码映射：[项目架构](docs/architecture.md)（[SVG 总图](docs/architecture.svg)）。

**研究目标（P7，总目标尚未完成，部分有限元/ROM/电驱联合已落地）：** 将开放有限元求解器与现有 PMSM/FOC、FMI、热网络、SIL 贯通，以同一台 PMSM 形成“电磁场提参→FOC 仿真→高保真热场→ROM/400 Hz 温度估计→控制 SIL”的可复现数字线程；按同等模型与误差条件对比开源组件与可合法获取的 ANSYS 求解器，不宣称已经完成有限元对标。[P7 专项路线图](docs/p7-open-fea-roadmap.md) · [总体路线图](docs/roadmap.md)。

## 验收约束

按用户 2026-10-23 的要求：仿真环境中完成并通过固定指标即可交付，真机由用户负责。
Agent 持续推进仿真/SIL 与可复现产物，不以板卡、PIL 或实测资源日志作为开发前置条件。
详见 [验收范围](docs/acceptance-scope.md)；证据等级仍按实际来源保留。

## 已实现的离线能力

- 原生 PMSM dq + 机械 RK4 模型；Clarke/Park、dq PI、回算抗积分饱和。
- 默认 20 kHz FOC、线性平均 SVPWM、静止电压保持、可选一周期延迟。
- B0 独立 DOP853/步长收敛；B1 阶跃、正反转速、参数偏差和失败工况。
- 五类 IR v0.1 Schema、单位/时钟/预算校验，native/PathSim 开环适配。
- 白名单实验工具、固定验收器、按内容寻址的账本和离线失败修复策略。
- double/float32 PI C 内核及主机 SIL；STM32G474 对象交叉编译流程。

这些是研究软件能力。当前未运行真实板卡 PIL；未提供 TI C2000 构建结果。
详细进度和确切证据见 [阶段状态](docs/stage-status.md)，总目标见 [路线图](docs/roadmap.md)。

## P6 多物理研究与交互报告

新增 9 状态关节耦合、三节点热网络、平均逆变器误差、
合成数据独立标定/验证与单节点 RC FMI 互操作。
[报告使用说明](docs/p6-report-guide.md)介绍离线 HTML、PDF、
PNG/SVG、CSV 和实际浏览器截图的下载与复现。

```bash
oeal simulate-joint examples/p6-joint.json --output outputs/joint
python benchmarks/validate_p6.py
python benchmarks/validate_fmi_thermal.py
python benchmarks/build_p6_report.py
```

报告包含工况/热阻切换、基准叠加、时间游标、参数说明与导出。
P6 合成研究数据不代表实测校准；完整范围见 [模型契约](docs/p6-model-contract.md)。

## 统一实验与控制设计

IR 0.2 的七个固定模型配置覆盖原生 FOC / 耦合关节、motulator 开关 PMSM、
上游非线性磁图、MuJoCo UR5e 单关节及固定 FMI 关节的外部 dq 电流主机。CLI、Agent 和评测共用同一执行接口。
IR 0.1 仍兼容。参数附单位，模型资产校验固定哈希，计算时钟与预算在执行前校验。
控制采样、关节宏步、求解波形与门极事件分别保留原始时间语义。

```bash
oeal list-models
oeal validate-spec examples/studies/native_foc_v1.json
oeal run-experiment examples/studies/native_foc_v1.json \
  --output outputs/study.json --csv-dir outputs/study-csv
```

完整环境使用 Python 3.12。含固定提交的 Menagerie 资产准备、许可证、完整证据
与离线交互报告的步骤见
[Unified studies and control design 工作流](.github/workflows/unified-design.yml)。

```bash
pip install -r benchmarks/design-requirements.txt
pip install -e ".[dev]"
python benchmarks/validate_open_models.py
oeal run-experiment examples/studies/ur5e_joint_v1.json \
  --assets-root outputs/open-models --output outputs/robot-study.json
python benchmarks/validate_unified_studies.py
python benchmarks/validate_design_iteration.py
```

准备资产前需按工作流将 Menagerie 固定提交检出至 vendor/menagerie。
python-control 提供降阶线性筛选；Optuna 在固定范围内仅调整位置 PD 增益；
SALib 做降阶 Morris 敏感度。平均逆变器训练后，在 PWM / 死区模型、齿隙和
额外 0.5 kg 载荷留出工况中重新验证。固定目标不会随搜索修改。
[开发与验收契约](docs/unified-studies-design-contract.md)列出范围、版本和门槛；
实际指标以对应 CI 的 outputs/design/report-data.json 为准。

报告增加搜索记录、原始/优化响应叠加、验证工况切换、组件状态回放及分析边界。
这仍是受保护的离线设计工具，不是已验收的在线通用 LLM 工程师。

## 能量端口与连续热模式

IR 0.2 新增可选 `energy_consistent=true`。它在同一求解器中积分六节点温度和
实际端口功率；额外器件热匹配直流并联耗能支路，转子摩擦进入机壳热端口。
默认旧模式保持兼容，首版能量模式限定线性 PMSM、恒压/电容母线及无夹具单关节。

```bash
oeal run-experiment examples/studies/energy-capacitor.json \
  --output outputs/energy-example.json --csv-dir outputs/energy-example
python benchmarks/validate_energy_accounting.py
```

完整环境与资产准备见
[能量工作流](.github/workflows/energy-evidence.yml)；
[固定方程、边界和验收](docs/energy-accounting-contract.md)解释局部余额与机器人接口误差。
新增 `energy` / `co_sim_energy` 结果流及交互报告，保留回馈的负功率和故障注入负例。
局部电驱—热通过不代表整个机器人已能量闭合。

## 可选中点转矩预测

UR5e 能量模式新增 `coupling_method=midpoint_predictor` 与
`robot_integrator=rk4`。它用完整质量矩阵的有效逆惯量、原力律的路径分段积分，
以及已完成宏步的真实转矩积分/时间矩做因果位移加权预测，
热量仍来自物理力律，弹性储能来自实际端点。默认 Jacobi / implicitfast 保持兼容。

```bash
oeal run-experiment examples/studies/ur5e-midpoint.json \
  --assets-root outputs/open-models --output outputs/midpoint.json \
  --csv-dir outputs/midpoint-csv
python benchmarks/validate_coupling.py
```

资产准备与环境见[耦合工作流](.github/workflows/coupling-evidence.yml)；
[预测方程与固定验收](docs/midpoint-coupling-contract.md)先于模型改动提交。
新增 `coupling` 宏步流记录预测、有效惯量、保持转矩、力律残差与回退。
首版验证无齿隙、无夹具且无激活约束的场景；遇到未覆盖分支会回退并使预测认证失败。
报告把同积分器耦合对照与积分器自身对照分开，不宣称全系统精确守恒。

## 快速运行

Python >=3.10；外部项目评测环境需 Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
python -m unittest discover -s tests -v
python -m pytest

oeal simulate examples/pmsm_step.json --output outputs/open-loop
oeal simulate-foc examples/foc_step.json --output outputs/foc
oeal validate-spec examples/ir/foc-experiment.json
oeal run-experiment examples/ir/foc-experiment.json --output outputs/ir-result.json
```

FOC trace.csv 包含时间、状态、实际保持电压、占空比、参考和限幅标志；
summary.json 包含独立重算指标、配置/轨迹散列和证据等级。
原始 PMSM 示例未为新后端修改。

## 重现阶段验收

在 Python 3.12 的独立环境运行：

```bash
python -m pip install -r benchmarks/requirements.txt
python -m pip install -e ".[dev]"
python benchmarks/validate_p1.py
python benchmarks/validate_p2.py
python benchmarks/validate_p3.py
python benchmarks/validate_p4.py
python benchmarks/evidence_manifest.py
```

P4 需要 GCC。固定上游提交、传递依赖 freeze、命令/版本、输入/产物散列、
轨迹、指标和失败案例均保存在 CI artifact。
P5 交叉编译需 ARM 工具链，运行 `python benchmarks/validate_p5.py`；
它只生成对象、反汇编和资源编译报告，不刷机、不测板端时间。

## 模型和执行边界

原生基准采用合成参数的平均电压模型；可选开源后端已包含开关事件、非线性磁图、
母线、机器人接触和六节点热网络。仍未实现真实 ADC/ISR 时序、用户设备参数辨识、
MuJoCo 关节 FMU 和全系统能量闭合；部分功率器件热估计尚未回写直流损耗。
电流指令限幅不保证瞬态真实电流限幅。
离线提议策略未测试在线 LLM；应用层白名单不是任意 Python 的 OS 沙箱。
P4 当前验证 double/float32 PI 内核，未验证完整嵌入式 FOC 或固定点。
交叉编译对象 size 不等于最终固件 Flash/RAM；板端 50 us 期限尚未测量。

## 文档

- [P1 评测计划](docs/p1-evaluation-plan.md) / [选型 ADR](docs/decisions/0001-simulator-and-model-interface.md)
- [FOC 时序与方程](docs/foc-contract.md) / [PI 契约](docs/current-controller.md)
- [IR 契约](docs/ir-v0.1.md) / [Agent 工具契约](docs/agent-tool-contract.md)
- [C/SIL 契约](docs/sil-contract.md) / [P5 部署与测量契约](docs/p5-deployment-contract.md)

MIT 许可证。第三方代码只在独立评测环境安装，采用结论和许可记录见 research/reviews。

## 长时热网络回放

`python benchmarks/validate_thermal_endurance.py` 运行一小时热源回放，
覆盖三种恒定环境与两种步长，并对照独立 ODE 与能量积分。
范围与固定判据见[验收契约](docs/thermal-endurance-contract.md)。
这不是一小时电机/机器人联合仿真。


## 秒级关节留出与状态报告

原九组 1–2 s PWM 轨迹/载荷/刚度留出由逐工况矩阵执行，
并增加七组 1 s 已知参数、平均模型/PWM、传感器与组合留出。
位置 PD 及原位置/电流/转矩目标冻结，独立审计使用全量原始流。
运行与报告见[联合工作流](.github/workflows/joint-robustness.yml)；
[原九组契约](docs/robot-endurance-contract.md) /
[七组联合契约](docs/joint-robustness-contract.md)。
实际通过范围与下载链接见[阶段状态](docs/stage-status.md)。

报告包含系统运行机制、时间回放、指标与失败原因、六组 PNG/SVG、PDF、
完整关节 CSV，以及单列的一小时预设热源回放。
这不是未知电机参数失配或整机耐久认证，真机由用户负责。


## 循环轨迹与电气参数失配

IR 0.2 的可选 `controller_parameters` 将名义电阻、电感和磁链与
真实 `model.parameters` 分离；未设置时沿用原行为。
可选 `settings.position_cycle_period_s` 启用从静止开始的余弦往复，
并要求全程峰值位置目标。参考公式与固定八组输入见
[循环与失配契约](docs/cyclic-mismatch-contract.md)。

运行 `python benchmarks/validate_cyclic_mismatch.py --case combined`，
再以独立进程运行 `python benchmarks/validate_cyclic_mismatch.py --audit combined`。
全部八组及报告由[专用工作流](.github/workflows/cyclic-mismatch.yml)复现。
报告展示冻结名义/真实参数、两个周期的全程峰值/RMSE、能量、状态回放和 CSV。
这只验证指定电气偏差，耦合器参数仍已知，不代表统计或长期鲁棒性。

## 九状态关节 FMI 交换模型

新增原创 FMI 2.0 CoSimulation 植物模型：PMSM dq、弹性双惯量及三节点热网络，
输出九状态、输入能量/负载做功/环境散热和轴转矩。主机写入旋转 dq 电压、
负载转矩与附加供电板热，按明确 ZOH 通信窗推进。
该独立 C 模型不替换现有 IR 配置，控制器由外部主机提供。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python benchmarks/validate_joint_fmi.py
python benchmarks/build_joint_fmi_report.py
```

需要 GCC；报告交互验收使用已安装的 Chrome。产物在 outputs/joint-fmi/ 与
outputs/joint-fmi-report/；后者解压打开 index.html，包含三图、PDF、完整 CSV、
运行机制/组件状态回放和 Linux x86_64 FMU。
[固定方程、端口和时钟契约](docs/joint-fmi-contract.md)先于实现提交，
[专用工作流](.github/workflows/joint-fmi.yml)保留独立 DOP853、步长减半、
接口错误检查与全部哈希；实际结果及下载见[阶段状态](docs/stage-status.md)。
固定合成参数和四组 0.08 s 实验不代表实测标定；
MuJoCo 整机 FMU、完整控制器/PWM 继续保留；OpenModelica 固定植物交换见下节。

## FMI 统一实验与外部电流闭环

`fmi_joint_v1` 通过既有 IR 0.2、CLI/API、StudyTools 与 CSV 导出运行。
外部 Python 主机复用电流 PI，固定每 50 us 采样并保持旋转 dq 电压，
可选一采样延迟；细分 FMI doStep 保留 <=5 us 实际端点波形。
四项目标同时检查尾段电流、真实细步电流峰值、轴转矩峰值和独立全域能量余额。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev,fmi]"
python benchmarks/validate_joint_fmi.py
oeal run-experiment examples/studies/fmi_joint_v1.json \
  --assets-root outputs/joint-fmi --output outputs/fmi-result.json \
  --csv-dir outputs/fmi-csv
python benchmarks/validate_fmi_host.py
python benchmarks/build_fmi_host_report.py
```

编译/独立参考及报告的完整环境仍使用 benchmarks/p6-requirements.txt 和 GCC/Chrome。
也可将已下载报告内的 oeal-joint.fmu 所在目录作为 --assets-root；
程序仅加载已独立验证的 Linux x86_64 二进制哈希，不接受实验指定代码或文件路径。
[实现前契约](docs/fmi-host-contract.md)与[专用工作流](.github/workflows/fmi-host.yml)
包含四组达标场景及一个电压不足的预期失败案例，三图报告明确显示真实结果。
植物物理参数仍固定；这是外部 dq 电流闭环，不包含位置环、PWM、
完整嵌入式 FOC、MuJoCo 或 OpenModelica 联调。

## 可配置电机 FMI 与位置伺服

新增 `fmi_servo_v2`：七个电机物理参数在初始化前配置，
电机电阻/凸极电感/磁链/极对数/惯量/粘性摩擦进入真实方程与能量核算。
控制器名义参数冻结；外部20kHz位置PD使用负载位置和电机输出侧速度反馈，
再驱动既有dq电流PI。传动与三节点热网络参数仍固定。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev,fmi]"
python benchmarks/validate_configurable_fmi.py
oeal run-experiment examples/studies/fmi_servo_v2.json \
  --assets-root outputs/configurable-fmi --output outputs/servo.json \
  --csv-dir outputs/servo-csv
python benchmarks/validate_fmi_servo.py
python benchmarks/build_fmi_servo_report.py
```

[实现前契约与反馈修订B](docs/fmi-servo-contract.md)记录原负载速度反馈结构A的
独立降阶判据，以及保留原增益/输入/门槛的电机侧速度反馈方案。
[专用工作流](.github/workflows/fmi-servo.yml)保留参数化植物证明、两种结构、
参数失配/反向/载荷/细步以及不可达案例的原始轨迹。
报告说明见[阶段状态](docs/stage-status.md)；四图报告包含主机/植物机制、
七参数实际与名义值对照、状态回放、完整控制CSV及Linux x86_64 FMU。
位置环使用理想模型状态；未覆盖编码器/PWM、MuJoCo整机或全参数范围稳定性。

## OpenModelica 模型交换与三方核验

新增原创 Modelica 九状态关节，由 OpenModelica v1.25.5 实际导出 FMI 2.0
**ModelExchange**。FMPy 导入生成二进制，主机按零阶保持通信窗用 DOP853 积分；
同一四组激励与独立 Python 方程、现有 C CoSimulation FMU 逐点比较。
这是独立交换验证路径，统一 IR 仍为七配置，旧资产白名单保持不变。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python benchmarks/build_openmodelica.py
python benchmarks/validate_openmodelica.py
python benchmarks/build_openmodelica_report.py
```

需 Docker（Linux x86_64 容器）、GCC 与 Chrome。
编译镜像已固定实际摘要，导出过程断网；包内保留生成源码、原始版权和契约。
[交换链路架构图](docs/openmodelica-exchange.svg) /
[实现前固定契约](docs/openmodelica-interop-contract.md) /
[实际结果与下载](docs/stage-status.md#2026-10-27openmodelica-model-exchange-三方验证)。
报告含三图/PDF、三方曲线、四组件状态回放、四组完整CSV和可导入FMU。
固定传动/热参数与四组短时合成输入，不代表实物精度或完整机器人交换。

## MSL 六节点热网络 FMU

用 **Modelica Standard Library 4.0.0 的真实物理组件**构建绕组/铁芯/壳体/
结温/板级/散热器网络，OpenModelica 1.25.5 导出 FMI2 ModelExchange。
六路独立保持损耗输入；内部绝对温度 K、输出 °C；提供有符号热流和输入/散热积分。
固定库提交与编译镜像，开源许可/实际组件源码随 FMU 留存。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python benchmarks/build_msl_thermal.py
python benchmarks/validate_msl_thermal.py
python benchmarks/build_msl_thermal_report.py
```

构建准备阶段需网络拉取/核对固定MSL源码与镜像；实际编译断网，需Docker/GCC/Chrome。
[实现前契约](docs/msl-thermal-contract.md) /
[真实组件连接图](docs/msl-thermal-network.svg) /
[采用记录](research/reviews/msl-thermal.md) /
[实际结果与下载](docs/stage-status.md)。
报告包含温度/加热冷却状态、带方向热流、工况/时间回放、六组完整CSV和四图PDF/PNG/SVG。
这是固定合成参数与预设损耗回放，不是整机一小时联合运行或实物热额定值验收；
统一IR仍为七配置。

## 电驱与 MSL 连续热反馈

在真实 motulator 电磁/逆变器模型上，新增可信 Python 热导数接口。
实际铜耗、器件耗散和转子摩擦进入 MSL 热 FMU；每个连续求解阶段
投影温度/能量状态，读取真实 `getDerivatives`，由同一上游求解器共同积分。
绕组温度同阶段修正实际电阻，控制器名义参数冻结；默认路径仍用原生热网络。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python -m pip install "motulator @ git+https://github.com/Aalto-Electric-Drives/motulator.git@2ffbf1ae52d5fadcdffd85d10c80dd15fd2e39fa"
git worktree add --detach outputs/msl-drive-base 65acdc66d3ccdcdfcee933c3e82b67c2a549cad4
python benchmarks/build_msl_thermal.py
python benchmarks/validate_msl_drive.py
python benchmarks/build_msl_drive_report.py
```

独立基线检出用于默认路径逐位兼容比较；构建环境仍需 Docker/GCC/Chrome。
[实现前契约](docs/msl-drive-contract.md) /
[连续联合架构图](docs/msl-drive-network.svg) /
[实际结果与报告下载](docs/stage-status.md)。
五图报告含电流/限幅、全部六节点温度、实际R、损耗/回馈、独立能量与故障注入。

可信 Python 调用使用 `make_drive(..., thermal_provider=对象)` 或
`run_drive(..., thermal_provider=对象)`，仅支持无机器人的 energy_consistent 模式。
对象提供 `evaluate(t, temperatures_c, heat_w, input_j, ambient_j, accepted=False)`
与 `describe()`；返回六个K/s热导数、输入功率W和环境散热W，核对形状/有限性/功率守恒。
调用者管理外部对象生命周期。该接口不允许实验JSON选择FMU或代码路径；
统一IR仍为七配置。

这是0.06–0.4s实际损耗联合仿真，区别于上一轮一小时预设损耗回放；
两者都不代表一小时整机或实物温度精度，真机由用户负责。

## MSL 非线性散热与风冷变化

新增真实MSL `Convection` 与 `BodyRadiation` 组件：
壳体仍经热阻散热，散热器通过对流和绝对Kelvin四次方辐射并联向环境散热。
外部Gc输入控制等效对流导热系数，Gr参数表示合成有效辐射面积；
输入热、壳体/对流/辐射三条散热积分和热储能分别审计。

```bash
python -m pip install -r benchmarks/p6-requirements.txt
python -m pip install -e ".[dev]"
python benchmarks/build_msl_cooling.py
python benchmarks/validate_msl_cooling.py
python benchmarks/build_msl_cooling_report.py
```

需Docker/Linux x86_64/Chrome；准备阶段拉取固定库/镜像，实际编译断网。
[冻结契约](docs/msl-cooling-contract.md) /
[散热架构图](docs/msl-cooling-network.svg) /
[实际结果与下载](docs/stage-status.md)。
五图报告可回放六节点温度、三条热流/能量去向、风冷正常/减弱/增强状态，
并导出六组全部CSV。六组一小时实验为预设热源回放；
新非线性边界尚未接入上一轮实际电驱提供方，旧七IR及线性FMU不变。

## 实际电驱与非线性MSL散热

继独立一小时热源回放后，新增实际motulator电驱损耗与Convection/BodyRadiation的同阶段联合反馈。
壳体、对流、辐射三条能量由电驱求解器分别积分，全部温度、热流、积分与源能独立核对。
新实验以六节点80°C合成初态激励散热，持续0.02–0.1s；不等同长时电机耐久。

```bash
python benchmarks/build_msl_cooling.py
python benchmarks/validate_msl_cooling_drive.py
python benchmarks/build_msl_cooling_drive_report.py
```

沿用MSL热编译依赖，另需固定motulator；完整基线检出与环境命令见
[专项工作流](.github/workflows/msl-cooling-drive.yml)。
[契约](docs/msl-cooling-drive-contract.md) /
[联合机制](docs/msl-cooling-drive-network.mmd) /
[实际结果与报告下载](docs/stage-status.md)。
默认25°C路径、旧线性FMU接口及七IR保持兼容。

## 可配置环境、初温与秒级实际电驱

真实MSL散热提供方支持ambient_c（−10..60°C）和六独立初温（−10..120°C）；
默认仍为环境25°C、六初温80°C。
冷启动实际电驱验证延长至1s，另含非均匀初态、冷热环境、
真实PWM与回馈，并保留原七组短时热初态回归。
配置及温度均为合成研究输入，真机由用户负责。

沿用前节编译和固定motulator依赖，完整命令与基线检出见
[专项工作流](.github/workflows/msl-configured-drive.yml)：

```bash
python benchmarks/build_msl_cooling.py
python benchmarks/validate_msl_configured_drive.py
python benchmarks/build_msl_configured_drive_report.py
```

[固定契约](docs/msl-configured-drive-contract.md) /
[可配置联合机制](docs/msl-configured-drive-network.svg) /
[结果及报告下载](docs/stage-status.md)。

## MSL热容/热阻配置与实际储热

独立OEALMSLParametric FMU支持六热容、五内部热阻及壳体环境热阻配置，
继续使用真实MSL组件。主机按实际C核算储能与功率，默认旧路径保持原算法。
[参数与复现说明](docs/msl-rc-configuration.md) /
[固定Gate](docs/msl-rc-contract.md) /
[架构图](docs/msl-rc-network.svg) /
[实际结果及报告下载](docs/stage-status.md)。

```bash
python benchmarks/build_msl_parametric.py
python benchmarks/build_msl_cooling.py
python benchmarks/validate_msl_rc_limits.py
python benchmarks/validate_msl_rc.py
python benchmarks/build_msl_rc_report.py
```

完整固定环境和基线检出见[工作流](.github/workflows/msl-rc.yml)。
三组零输入矩阵指数与七组短时实际电驱分开验收，报告含实际C/R、组件状态和全量CSV。
参数为合成研究输入，真机由用户负责。

## 六节点热参数合成辨识

从真实MSL热激励数据估计六C、五内部R和Rcase：
训练测量带0.02K合成噪声，SciPy有界积分最小二乘仅使用train；
参数冻结后在独立验证和60°C留出上加载新FMU预测，并与Radau核对。
[固定契约](docs/msl-identification-contract.md) /
[方法与复现](docs/msl-identification.md) /
[隔离架构](docs/msl-identification-network.svg) /
[实际结果及报告](docs/stage-status.md)。

```bash
python benchmarks/build_msl_parametric.py
python benchmarks/generate_msl_identification.py
python benchmarks/fit_msl_identification.py
python benchmarks/validate_msl_identification.py
python benchmarks/build_msl_identification_report.py
```

完整固定环境见[工作流](.github/workflows/msl-identification.yml)。
报告含五图、十二参数、验证/留出六节点回放与完整CSV。
适用范围为六温度全观测、已知热源和匹配结构的仿真内辨识；真机由用户负责。

## 热辨识可靠边界：20组训练扰动

[实际结果与复现](docs/msl-identification-robustness.md) /
[固定契约](docs/msl-identification-robustness-contract.md) /
[四图离线交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40834099841/artifacts/12880012724)。

三档噪声各四个种子，另含温度偏置、热源记录误差、缺失观测及无激励案例。
优化器成功与合成适用性分别显示：20组中18组返回参数，10组通过固定合成门槛。
报告提供六节点状态/传热机制回放、十二参数、完整预测CSV及PDF。
恒温噪声仍可能产生满秩，因此秩/条件数不能替代观测质量与独立预测检查。
评价使用合成真值，不是实测故障检测器；完整命令及证据见上述说明。

## 训练观测与预测可信性分层报告

[五图交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40908576468/artifacts/12912184941) /
[诊断规则与实际验证](docs/thermal-observation-quality.md) /
[接入固定契约](docs/msl-quality-report-contract.md)。

20组MSL训练扰动分别显示观测幅度诊断、优化器状态与合成适用性。
六通道跨度及门槛可查；恒温噪声提示幅度不足。
17组幅度支持中仍有7组独立评价不适用，不把幅度支持当作参数可信。
报告可离线回放六节点状态/热流，附全量CSV、拟合JSON、PDF及图像。

## P7-A：真实有限元基准

[方法与实际结果](docs/p7-fea-baseline.md) /
[四图交互报告（2.84MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40980679597/artifacts/12944601783) /
[固定验收契约](docs/p7-fea-baseline-contract.md)。

Gmsh真实网格→scikit-fem稳态导热→独立制造解，三档全场误差接近二阶收敛，
最细温升L2相对误差0.2701%。报告可切换网格、查看节点温度/误差和热源—边界散热机制，
附MSH/VTU/CSV及PDF/PNG/SVG。仅P7-A部分数值基准，不代表电机FE或实物热精度。

## 双材料有限元与混合热边界

[方法与实际结果](docs/p7-layered.md) /
[四图交互报告（3.72MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40983494657/artifacts/12945314205) /
[固定契约](docs/p7-layered-contract.md)。

三工况×三网格，真实材料标签、恒温/对流/绝热边界与解析对照。
报告区分温度误差、能量余额和界面两侧热流差，保留环境反向入热，
提供全部MSH/VTU/节点和界面CSV。
局部热流仍有离散误差；当前为理想二维稳态基准，不是实物热模型或ROM。

## RT0守恒通量后处理

[方法与独立验收](docs/p7-conservative.md) /
[四图交互报告（7.07MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40986556408/artifacts/12947825322) /
[固定契约](docs/p7-conservative-contract.md)。

保留原P1温度，增加逐单元守恒与界面局部通量评价。
异质材料最细局部界面RMS由17.11%降至0.0412%，
但九组全域通量L2均比原梯度更大，报告显著披露这一取舍，不全面替换原通量。
可查看单元通量/源/余额、原/新误差，下载cell/facet/interface CSV、VTU和RT系数。

## BDM1：守恒与全域通量精度

[方法与三方实际结果](docs/p7-bdm.md) /
[四图交互报告（9.44MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40989152180/artifacts/12947609522) /
[固定契约](docs/p7-bdm-contract.md)。

九组合均优于原P1和RT0全域通量误差；最细异质材料全域L2由
P1的1.704%、RT0的2.416%降至BDM1的0.01987%，界面局部RMS约0.0412%。
保留原温度与三方数据；BDM线性边界迹与RT0面平均的区别明确展示。
包含单元状态、实际网格、逐点界面CSV、VTU、系数/DOF矩映射和PDF。
这是理想二维稳态制造解的可选后处理，不是工程实测精度或ROM验收。

## 有限接触热阻：界面温度可跳变

[方法与十二组合结果](docs/p7-contact.md) /
[三图交互报告（3.10MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41029554337/artifacts/12964574954) /
[冻结契约](docs/p7-contact-contract.md)。

新可选P1基准保留材料界面左右独立温度，通过面比热阻耦合。
三档热阻和热环境共十二组合、三档网格近二阶温度收敛，最细温升L2约0.011%–0.012%。
报告显示温差、带方向热流、两区运行机制及能量余额，附全部CSV/VTU/稀疏矩阵。
零源串联规律与反向入热通过；仍是理想稳态数学基准，瞬态/工程热场/ROM继续推进。

## 瞬态有限元：从加热到储热与冷却

[方法、时间/空间独立验证](docs/p7-transient.md) /
[四图交互报告（78.68MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41081364479/artifacts/12990091219) /
[冻结契约](docs/p7-transient-contract.md)。

新增一致质量矩阵与有限接触热阻瞬态，九个网格/时间步组合覆盖0–16s。
时间阶数约2，空间阶数约1.99；最细五时刻温升RMS对独立FV参考约0.0255%。
报告可回放两区温度/储能、源开关、接触热流及环境散热，附完整节点/时间CSV、矩阵/场与PDF。
同FE模态时间参考和独立空间参考分别标明；合成理想基准，尚非工程器件或ROM。

## pyMOR：有限元降阶与独立留出

[方法、误差与性能范围](docs/p7-rom.md) /
[四图交互报告（74.28MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41367738173/artifacts/13106884974) /
[冻结契约](docs/p7-rom-contract.md)。

实际pyMOR质量POD加两区能量测试向量，将2145自由状态降至14维。
训练基底/hash冻结后生成验证和留出；留出对同离散全阶模型峰差2.02e−5K。
Rc失配域外拒绝，反事实峰差0.853K；保持自身守恒不能代替参数匹配。
本宿主更新+六输出p95为7.61μs，全场重建另计；未完成板端或20kHz同步。
报告可回放两区温度/储能/热流并导出完整场、基底、矩阵、CSV和PDF；仍为合成理想模型。

## 接触参数ROM与纯NumPy推理接口

[方法、适用域及接口示例](docs/p7-param-rom.md) /
[八案例交互报告（177.53MB，含完整场）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41369969789/artifacts/13108342832) /
[冻结契约](docs/p7-param-rom-contract.md)。

六组训练冻结为22维仿射模型，六个新Rc点全部通过，
对同时间离散全阶模型最大节点差3.31e−5K。
新增NumPy-only AffineThermalROM：加载模型时实际检查范围/矩阵，非法输入不推进状态。
Rc声明范围[.01,1]m²K/W；域外两个反事实虽误差较小仍拒绝，不据此扩大范围。
实际step含校验和六绝对物理输出，宿主p95为26.7–27.9μs；尚非板端或FOC时钟验收。

## 实际电驱20kHz与热ROM400Hz事件同步

[模型、窗口能量与适配说明](docs/p7-multirate.md) /
[四案例交互报告（41.59MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41373683102/artifacts/13110586078) /
[冻结契约](docs/p7-multirate-contract.md)。

复用实际motulator平均桥/PMSM与既有FOC，铜/桥真实RHS积分每50控制周期关闭一次热窗口，
先热更新/R(T)更新，再发新命令。每组5000控制命令、100次400Hz热更新，
另含冻结R、800Hz细化和回馈，末窗口不丢、不把均值再平均。
桥近零方向锁存的负耗散失败已保留，采用明确的上游平滑方向刷新适配后通过。
205测试通过/8跳过；报告可回放温度年龄/窗口进度/电流/R和能量。
仍是实际开源电驱与合成等效板的离线联跑，不是器件测温、PWM或实时硬件证明。

## 两秒负载循环、外部制动冷却与暖状态续跑

[方法及实际结果](docs/p7-drive-cycle.md) /
[四图交互报告（47.85MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41383452758/artifacts/13115095141) /
[固定契约](docs/p7-drive-cycle-contract.md)。

四组实际motulator/FOC与热ROM联合，每组40000控制命令；
两次非热窗边界暂停后同对象继续，与连续运行受检状态最大差为0。
1→2s板内储热下降18.84%；电流控制仍启用，外部机械制动耗散单独记账。
报告可回放阶段、保持温度/年龄、电流/R、储热/散热与余额，附12份完整CSV。
页面每25tick加关键边界抽样，原始RHS/完整FE与ROM场在独立353.34MB证据包。
这是2s合成等效板联合验证，不是关栅故障、跨进程恢复或耐久；真机由用户负责。

## 磁静态场、方向与电感提取基准

[方法、误差和失败记录](docs/p7-magnetic.md) /
[四图离线交互报告（5.58MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41398648374/artifacts/13120940769) /
[固定物理契约](docs/p7-magnetic-contract.md)。

真实Gmsh/scikit-fem求解有符号去回流电流的Az场，导出B/H、磁能、磁链和有单位电感JSON。
四工况×三网格通过独立解析/收敛、反向/倍流/零电流、规范和故障检查；
最细电感误差≤0.0737%，B全场误差≤2.7200%，分别披露。
原固定对角线粗网格界面失败保留，交替网格在相同门槛下通过，旧热基准及网格hash保持。
报告可切换Az/By/Hy、节点/单元状态、36CSV与12电感JSON，附VTU/NPZ/PDF/PNG/SVG。
这是有限矩形线性磁路的部分P7-A，不是PMSM电磁场或Ld/Lq，未写入现有FOC。

## 实际FEMM永磁电机参数到FOC

[方法、结果与复现](docs/p7-femm-motor.md) /
[五图离线交互报告（2.26 MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41411974413/artifacts/13125954296) /
[固定契约](docs/p7-femm-motor-contract.md)。

真实FEMM三网格、243个静态电机场提取ψ=0.02602778 Wb、
Ld/Lq≈31.3056 μH，再用冻结参数运行现有motulator正反向FOC。
报告可查看磁化角、绕组电流、气隙B、磁链/转矩和控制状态，
附14份全量CSV、精确参数JSON、PDF/PNG/SVG；原生fem/ans在独立证据包。
最终227测试通过、12跳过，8个CI检查成功。
这是线性无槽合成电机的部分P7-B；原失败粗网格与FOC配置错误保留，
工程槽结构、饱和、损耗到热场映射及完整固件仿真仍待推进。
FEMM/pyfemm为AFPL，许可及不再分发二进制的范围见采用评审。

## 非线性FEMM二维磁图与训练冻结

[方法与实际结果](docs/p7-femm-nonlinear.md) /
[五图离线交互报告（1.38 MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41582088865/artifacts/13205733362) /
[实现前契约](docs/p7-femm-nonlinear-contract.md)。

真实FEMM合成饱和材料、两网格50个训练点冻结后，独立执行留出、局部增量、
角度与线性配对。最细零点Ld/Lq≈29.4893/31.1690 μH，
四个留出最大磁链差1.382 μWb；误差定义与适用范围见方法说明。
报告可查看82个静态状态、绕组电流、气隙B及定子采样B/H，
导出9CSV、2磁图JSON和PDF/PNG/SVG；234测试通过、12跳过，浏览器验收通过。
这是部分P7-B的合成静态磁图，未接入动态非线性FOC；
工程槽结构、真实材料与损耗到热场映射仍待推进。

## 公开有槽电机：PYLEECAN实际模型与原生磁场

[方法、数据和失败修复](docs/p7-pyleecan.md) /
[五图离线交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41597944903/artifacts/13212872914) /
[先行固定契约](docs/p7-pyleecan-contract.md)。

实际调用固定PYLEECAN/SWAT-EM公开SPMSM_001，12槽8极、44点非线性材料，
三网格与指定转角/双叠长共12静态解，24原生fem/ans全部验收。
中→细磁链差/0.05Wb为0.133%，转矩差0.00419N·m；
明确原生1m与物理50mm叠长，逐点核验实际22.5°初始对齐。
报告可选工况、点击24线圈边查看相/匝/电流/安匝，显示实际磁体与气隙场、
磁链/转矩/区域状态，提供15CSV、3JSON及PDF/PNG/SVG。
材料测量出处未独立确认，公开模型轴向参数不一致单列；
这是部分P7-B静磁验证，尚未连接同机型动态FOC或损耗到工程热场。

## 公开有槽电机：实际角扫描与开路反电势

[方法、结果及原生证据](docs/p7-pyleecan-angle.md) /
[离线交互报告（1.78MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41604212881/artifacts/13215188942) /
[实现前契约](docs/p7-pyleecan-angle-contract.md)。

同一公开SPMSM_001通过三档网格、每档13个转角共39个真实静磁解，
保留78个原生fem/ans，按e=−ωdλ/dθ推导开路准静态电压。
600rpm细网格采样绝对峰值约15.959V；中细网格电压差最大0.01527V，
但7.5°与15°角步差最大1.826V，明确显示采样限制。
报告可切角度/网格/转速，查看真实槽形、磁体、线圈和气隙场，
并导出CSV/JSON、图表PDF/PNG/SVG。两图与浏览器交互验收通过。
这不是时步运动、动态FOC或实物反电势验证；更细角步和独立参考仍待完成。

## 2026-11-04：公开电机角步由7.5°细化至3.75°

[方法与实际证据](docs/p7-angle-refinement.md) / [离线报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41764534832/artifacts/13292001945)。
同一细网格新增12个中间角真实场，与已核验旧点构成24角周期。
共同角度电压差由上一轮1.82619V降至0.696911V，差值缩小2.6204倍；
600rpm离散峰值16.30349V。全部固定门槛、237项原生环境测试和正式浏览器检查通过。
202个manifest条目与新旧50份原生文件核验；复用与新求解来源逐点保留。
差值改善不等于连续/实物精度或收敛阶，仍为部分P7-B准静态开路序列。

## 2026-11-04：公开电机开路dq零位与留出验证

[方法与冻结证据](docs/p7-dq-calibration.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41773934220/artifacts/13295853792)。
仅用旧12角拟合正向p=4电角零位，冻结后用新增12中间角验证；保留零序及实际q残差。
δ=−3.0698798e−5rad，训练幅值0.06548295Wb，留出最大q残差0.302232mWb，
d偏差0.107709mWb，abc往返差1.39e−17Wb；解析交换B/C反例被拒绝。
226测试通过37可选跳过；正式浏览器24角/CSV/390px验收通过。
这是开路坐标标定，主控制器尚未接入，非带载磁图、动态FOC或实测精度。

## 2026-11-04：公开电机带载dq方向与转矩

[方法与真实结果](docs/p7-loaded-frame.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41806414795/artifacts/13310346005)。
固定开路零位，两个机械位置各五种dq电流，共10个新FEMM非线性静态解。
原始电路回读参与dq核对；±2A q轴增量转矩方向正确，纯d轴转矩变化≤4.25e−5Nm。
FE增量与dq近似最大差0.033731Nm，位置相关差异完整保留。
原生251测试通过25可选跳过；正式报告239通过37跳过，10状态/CSV/390px验收通过。
两个44项manifest及20原生文件核验；仍为静态低电流接口验证，动态FOC/全磁图/损耗和工程热映射继续推进。

## 2026-11-05：公开电机局部磁链模型与冻结留出

[方法和范围](docs/p7-local-flux.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41947340580/artifacts/13379910369)。
只用0°五个真实带载点拟合ψ和对称正定L，冻结后评价22.5°五点。
Ldd/Lqq约1.12057/1.35461mH，留出最大磁链向量差260.94μWb，
对FE增量的近似转矩差≤0.0337701Nm；原始互易残差与零流q磁链均保留。
245测试及正式浏览器验收通过，输入域外拒绝。
本轮重新核验旧场而无新FE求解，模型只覆盖已声明局部静态范围，动态FOC未接入。

## 2026-11-05：冻结局部模型进入锁转子电流环

[方程、参数与真实积分结果](docs/p7-locked.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41975506070/artifacts/13391706312)。
复用既有PI/坐标变换/平均SVPWM，保留完整2×2电感矩阵；固定角度/零速，电阻0.3Ω单独指定。
正常与欠压各40ms、800控制命令、801端点；正常稳定段iq误差≤71.71μA。
矩阵指数同电压重放、5/2.5μs细化与能量均通过；欠压780次限幅，最大稳定误差0.1784A，明确未达跟踪目标。
259测试、八项CI及正式浏览器检查通过；原模型SHA不变，无新FE求解。
这是合成锁转子电流环验证，未完成旋转FOC、动态物理精度、完整固件或工程热映射。

## 2026-11-05：局部模型的外部恒速旋转扩展

[方程、假设与结果](docs/p7-rotation.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41978284329/artifacts/13393080706)。
明确假设冻结局部dq模型转角不变，外部施加±300rpm，既有20kHz PI/SVPWM与完整ωJλ耦合进入动态RHS。
正常各60ms/1200命令/1201端点，最大稳定iq误差约16.2μA；独立增广矩阵指数、半步长和源/铜/轴/储能余额通过。
欠压6V在约0.595ms积分阶段离域拒绝，保留12命令、13有效轨迹点及首个非法阶段，不裁剪继续运行。
261测试、八项CI和四工况浏览器验收通过。
无新增FE；原带载仅两角验证，合成延拓的数值结果不构成全角度动态物理精度认证。真实机械ODE、完整固件及工程热映射继续推进。

## 2026-11-05：公开电机八角带载留出验证

[方法与实际结果](docs/p7-angular.md) / [交互报告（1.74MB）](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41985661797/artifacts/13396280327)。
固定ψ/L与dq零位，新增六角×五电流=30个真实FEMM解，与原10例组成八角40点。
新六角不参与拟合；5训练、5原留出、30新留出的角色和来源逐点保留。
全部通过原预算，最大磁链向量差397.879μWb（预算1mWb）、转矩增量差0.0337701Nm（预算0.10Nm）。
八包各44项manifest、80份原生fem/ans完整核验；证据完整性和模型支持分别判定。
报告254测试通过/37可选跳过，浏览器40状态、三种精确下载、390px验收通过。
这是离散静态角点证据，仍未认证连续角域、带载角步/网格收敛、独立物理精度或完整Gate B。
下一步推进混合dq电流/幅值留出及细化，再判断角度相关动态接口与同机型损耗热映射。

## 2026-11-05：混合dq电流与幅值留出

[方法与结果](docs/p7-current-holdout.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41992584303/artifacts/13399460757)。
四角新增32个真实FEMM解，覆盖±0.5A单轴及(±1,±1)A混合电流；与20个核验旧锚点共52例，固定模型未重拟合。
新增32点均通过，最大磁链差380.296μWb（预算1mWb）、转矩增量差0.01755165Nm（预算0.10Nm）。
全部52点也通过；原生/旧证据重验、篡改/缺点/错来源反例、254测试及52状态浏览器检查通过。
离散静态通过不代表连续电流域、带载网格/角步收敛、动态FE或完整Gate B；真机由用户负责。

## 2026-11-05：公开电机带载三档网格敏感性

[方法与结果](docs/p7-loaded-mesh.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41995793750/artifacts/13400123591)。
四角四电流、三档网格共48工况，其中32个粗/中网格为新FEMM解，细网格16点经核验复用。
16组均通过预算，中→细最大磁链差67.205μWb、最大绝对转矩差0.0024973Nm；同网格零流扣除后的增量转矩最大差0.0016043Nm。
全部节点逐档增加；两次差值及非单调标记保留。257测试及48状态浏览器验收通过。
这是离散2D静磁网格敏感性，不是连续角/电流、动态场或实物精度认证。带载角步和同机型动态接口继续推进。

## 2026-11-05：带载角步细化、网格复核和角度相关控制接口

[方法、失败记录和完整证据](docs/p7-angle-dynamics.md) / [交互报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/42004300771/artifacts/13404795726)。
连续新增140个真实FEMM场（含8个中点网格复核），复用并审计旧场；带载绝对转矩与零流扣除增量分开。
零流/+2A相同两种工况的四级中点最大绝对转矩差为1.9373、1.0105、0.2985、0.08293Nm；前三级未达0.10Nm预算，最细级64点全部通过。
四中点两档网格最大转矩差0.002219Nm，不能替代实物或独立场参照；固定局部模型在首级36点的增量预算通过。
角度相关ψ与固定L接入既有20kHz PI/平均SVPWM，正反转、矩阵指数重放、半步长、能量和欠压离域拒绝通过；零流齿槽转矩及真实机械动态未建模。
275测试通过/25可选跳过，报告验200个场选择状态、18个动态/控制状态及20种精确下载。
仅为离散2D静磁与合成动态证据；连续域、物理精度、完整Gate B及工程热映射仍待完成，真机由用户负责。


### P7 齿槽转矩与机械联合仿真（2026-11-05）

新增 FEMM 零电流齿槽转矩拟合、原生共能与应力转矩交叉检查、含转子机械方程的电流控制仿真，以及可交互的模型与能量报告。结果与局限见 [P7 齿槽转矩与共能](docs/p7-cogging-coenergy.md)。
