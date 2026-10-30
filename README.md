# Open Engineering Agent Lab

面向 PMSM / FOC / 机器人关节研究的 Python + Agent 工程实验仓库。
参数和工况使用开放 JSON，仿真输出 CSV/JSON，验收与提议策略分离。

项目总图、运行机制与源码映射：[项目架构](docs/architecture.md)（[SVG 总图](docs/architecture.svg)）。

**新增研究目标（P7，尚未实现）：** 将开放有限元求解器与现有 PMSM/FOC、FMI、热网络、SIL 贯通，以同一台 PMSM 形成“电磁场提参→FOC 仿真→高保真热场→ROM/400 Hz 温度估计→控制 SIL”的可复现数字线程；按同等模型与误差条件对比开源组件与可合法获取的 ANSYS 求解器，不宣称已经完成有限元对标。[P7 专项路线图](docs/p7-open-fea-roadmap.md) · [总体路线图](docs/roadmap.md)。

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
