# Open Engineering Agent Lab

面向 PMSM / FOC / 机器人关节研究的 Python + Agent 工程实验仓库。
参数和工况使用开放 JSON，仿真输出 CSV/JSON，验收与提议策略分离。

项目总图、运行机制与源码映射：[项目架构](docs/architecture.md)（[SVG 总图](docs/architecture.svg)）。

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

IR 0.2 的五个固定模型配置覆盖原生 FOC / 耦合关节、motulator 开关 PMSM、
上游非线性磁图和 MuJoCo UR5e 单关节。CLI、Agent 和评测共用同一执行接口。
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
完整关节 FMU 和全系统能量闭合；部分功率器件热估计尚未回写直流损耗。
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
