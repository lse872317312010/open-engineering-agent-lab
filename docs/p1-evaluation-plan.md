# P1 执行计划：开源内核选型 + 可验证 PMSM-FOC 基准

> 从 [总路线图](roadmap.md) 拆出的首轮可执行研究计划。  
> 更新日期：2026-10-22；**当前为计划，不是已经完成的评测结果。**

## A. 研究问题

1. 是否可以用现有 Python 仿真组件实现确定性的连续电机模型 + 20 kHz 离散控制器？
2. 是否能保留自有模型规范，不与某个工具的私有 JSON 或运行时对象绑定？
3. 是否支持后续 120 kHz PWM、ADC 触发、编码器/ISR 延迟、饱和和多速率事件？
4. Agent 能否通过无界面、可审计的 API 修改模型和运行测试，同时避免任意代码执行？
5. 开源协议、维护成本和依赖体系是否允许长期自由使用、修改及商业开发？

## B. 候选项目与试验顺序

| 顺序 | 项目 | 上游 | 重点核查 |
|---|---|---|---|
| 1 | PathSim | https://github.com/pathsim/pathsim | 方程/框图 API、事件、多速率、求解精度与状态复位 |
| 2 | motulator | https://github.com/Aalto-Electric-Drives/motulator | PMSM、控制器、逆变器模型正确性和可拆解性 |
| 3 | Agentic Embedded Lab | https://github.com/eust-w/agentic-embedded-lab | 仿真任务/产物/证据编排、Agent API 和安全边界 |
| 4 | Mavrith | https://github.com/Yuzhe-Xu/Mavrith | 模型端口/类型/采样率语义和机器可读拓扑 |
| 5 | PathView | https://github.com/pathsim/pathview | 可视化模型导入/导出、版本兼容与可替换性 |
| 6 | OpenModelica + FMI | https://github.com/OpenModelica/OpenModelica | 可选多物理后端与 FMU 互操作成本 |
| 7 | SemaPLC | https://github.com/midea-ai/SemaPLC | 编译—运行—验证工作流参考；非 FOC 建模后端 |

> 对每项保留“不采用”的空间，不预设最终技术选型；在确认许可证后才能引入源码或依赖。

## C. 统一评测流程

对每个候选建独立记录 `research/reviews/<project>.md`，必须包含：

- 上游 URL、评测日期、版本/commit、许可证及其例外/第三方依赖；
- 安装命令、Python/OS/CPU、锁定的版本、可复现运行日志；
- 无界面创建/读取/更新模型的 API，模型和实验能否导出为开放格式；
- 求解器、事件/零交叉、多速率、代数环、状态重置、错误反馈的真实行为；
- 独立数学参考的误差（不是两个库互相证明）及步长收敛；
- 同样的输入参数下：运行耗时、峰值 RAM、失败案例、数值稳定区间；
- Agent 执行权限/模型解析安全性，是否会执行任意 Python；
- 结论：`adopt` / `adapt` / `reference-only` / `reject`，记录理由、限制和后续动作。

**硬性否决条件：** 许可证不允许目标用途；无法无界面自动运行；不可接受的不可控代码执行；模型语义不透明且不可复现。性能评分不得取代硬性门槛。

## D. 建议基准用例（B0–B3）

### B0：现有 PMSM 开环数值基准

- 复用仓库 `examples/pmsm_step.json`，不得直接更改现有黄金用例来迁就新后端。
- 建立固定 `R_s, L_d, L_q, \psi_f, p, J, B, u_d, u_q, T_L` 参数集，明确单位。
- 与独立的解析极限/高精度参考进行对照；比较末态、峰值、扭矩、状态积分一致性。
- 数值精度通过 **步长减半收敛** 与规定容差检查；记录积分方法及运行时间。

### B1：20 kHz 离散电流环（MVP 核心）

- 电流环：`T_s = 50 us`；参考 `i_d^*=0 A`，`i_q^*: 0 -> 5 A`；
- PI 要定义明确的离散差分方程、积分/限幅/抗饱和顺序和初始状态；
- 初期使用平均值逆变器，电压矢量限制 `|u_dq| <= Vdc/sqrt(3)`（线性 SVPWM 近似）；
- 对比阶跃稳态误差、超调、调节时间、饱和持续时间和模型约束违反次数；
- 用独立 RL 解析极限、零速与非零速案例检查方程和控制行为；
- 结果包含轨迹、采样时间定义、参数来源、指标脚本以及数值容差理由。

### B2：离散事件与控制时序（后续精细化）

- 在 B1 基础上分别引入**一个采样周期计算延迟**、PWM 更新生效时刻和 ADC 采样点；
- 研究 120 kHz PWM 与 20 kHz FOC 的多速率调度，不能用平均值模型假装开关细节已验证；
- 关注执行顺序不一致导致的波形差异，记录各后端事件语义；
- 初期仅作可行性试验，不把事件模型等同于 MCU 时序测量。

### B3：固件对照预备（正式 Gate 在 P4）

- 明确控制器输入/状态/输出结构与单位；
- 设计确定性共享测试向量，为后续 Python↔C 逐步比较准备；
- 在 P1 **不要求**提供已验证的真实 MCU 或 SIL 结果。

## E. 首轮产物与目录约定（拟新增）

```text
docs/
  roadmap.md                    # 总路线图
  p1-evaluation-plan.md         # 本文
  decisions/
    0001-simulator-selection.md # 证据充分后再填写选型决策
research/
  reviews/
    pathsim.md
    motulator.md
    agentic-embedded-lab.md
    mavrith.md
benchmarks/
  b0-open-loop/
  b1-current-loop/
  b2-timing-semantics/
experiments/
  <date>-<case>/
    question.md
    input.json
    summary.json
    result.md
```

目录代表**计划中的组织方式**，未创建的文件不得被描述为已存在。大的仿真轨迹可保存在可再生的外部存储，但要保留输入、版本和可验证摘要。

## F. 执行顺序（Issue/PR 可按此拆分）

- [x] **P1-01** 检查远程 CI：Python 3.10–3.12 的构建/测试结果和可复现命令。
- [x] **P1-02** 固定 B0 工况、独立数学参考及误差指标脚本。
- [x] **P1-03** PathSim 最小接入试验：B0 + 无界面 API + 多速率/事件能力检查。
- [x] **P1-04** motulator 最小接入试验：电机模型和 B1 控制参考对比。
- [x] **P1-05** 评审 Agentic Embedded Lab / Mavrith：可复用接口、数据/证据模型和许可。
- [x] **P1-06** 在 OEAL 原生代码中构建 B1 20 kHz FOC 与独立测试。
- [x] **P1-07** 执行 B2 时序语义探索，明确适配代价。
- [x] **P1-08** 汇总对比、形成 ADR，制定 P2 IR 的最小语义契约。

## G. P1 Gate：完成条件

**必须同时满足：**
1. 至少 PathSim、motulator 和 Agentic Embedded Lab 有可核对的版本、许可、安装/运行记录与明确结论。
2. B0 和 B1 在干净 Python 环境可重跑；误差与控制指标由**独立测试代码**计算。
3. 对关键不适用工况和未覆盖风险有明确披露，不仅展示一次成功仿真。
4. 形成已审阅的仿真器/工程接口选型 ADR，说明为什么选、为什么不选。
5. CI 记录包含确切 commit、Python 版本和测试日志；没有真实 MCU 证据就不写“PIL/硬实时已验证”。

通过后进入 P2 的模型 IR v0.1 设计。允许提前做 Agent 与 UI 的隔离 PoC，但它们不能绕开此 Gate。

## H. 本轮执行范围与证据

2026-10-22 已完成本轮有限采用范围的评测；Gate 工程评审与决策见
[ADR 0001](decisions/0001-simulator-and-model-interface.md)，运行证据见 [阶段状态](stage-status.md)。
P1-04 是电机方程/RL 模型探针，未验证 motulator 完整控制栈；
P1-05 仅验证 AEL schema 和 Mavrith typed-port API，均为 reference-only；
P1-07 为排程与单周期延迟探索，不是 PWM/ADC 开关级验证。
原有 main CI 曾因 import lint 失败，工作分支已修复并核验，尚未合并。
