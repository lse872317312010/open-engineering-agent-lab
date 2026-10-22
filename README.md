# Open Engineering Agent Lab

面向电机控制与机器人关节研发的开放式 Python 研究基地。项目先用一个可验证的 PMSM dq 模型打通
“参数化工况 → 可重复仿真 → 结构化结果 → 自动测试”链路，再逐步接入控制器、热模型、动力学和
Agent 工作流。模型、数据和实验记录采用可读、可迁移的开放格式，不依赖某一家商业建模环境或模型服务。

## 当前能力

- PMSM 转子坐标系 dq 电气方程与机械运动方程，使用固定步长 RK4 积分。
- JSON 工况输入，命令行执行，导出 CSV 轨迹和 JSON 摘要，方便脚本或 Agent 调用。
- pytest 数值与 CLI 测试，以及 Python 3.10–3.12 的 GitHub Actions 检查。
- 核心仿真只依赖 NumPy；Agent/LLM 不属于运行仿真的必需依赖。

这是研究用的平均电压模型，当前不包含开关级逆变器、采样/PWM 时序、饱和、损耗、温升或真实电机参数辨识。
结果不能直接用于硬件安全判断或量产参数定型。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
```

运行样例：

```bash
oeal simulate examples/pmsm_step.json --output outputs/pmsm_step
# 也可以：python -m oeal simulate examples/pmsm_step.json --output outputs/pmsm_step
```

输出目录包含：

- `trace.csv`：每个仿真步的时间、电流、机械转速/角度和电磁转矩。
- `summary.json`：输入参数、采样设置、末态及峰值摘要，并记录包版本、输入配置 SHA-256 和积分方法。

## 面向 Agent 的调用约定

Agent 以仓库内 JSON 工况作为显式输入，通过 `oeal simulate` 执行，不直接改动模型内部状态。每次实验应保存：

1. 输入工况 JSON 和代码版本（后续实验记录会自动补齐）。
2. 仿真轨迹与摘要文件。
3. 由验证脚本计算的指标、约束是否通过，以及失败原因。

这样可以把“提出假设/选择参数”的模型推理与“数值求解/验收”的确定性工具分开。后续 Agent 适配通过薄接口加入，
不把某个云端 API、账号或编排框架写进模型核心。

## 目录

```text
src/oeal/models/     物理模型与数值积分
examples/            可直接运行的输入工况
tests/               方程、积分和命令行回归测试
docs/                模型边界、设计原则和路线图
experiments/         实验记录格式约定
.github/workflows/   持续集成
```

## 研发路线

路线见 [`docs/roadmap.md`](docs/roadmap.md)。第一阶段优先建立数值可信度和实验可重复性，再扩展到 FOC 与多物理场；
每次扩展都需要先给出模型假设、单位、有效范围和独立验证案例。

