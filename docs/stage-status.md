# 阶段状态与证据索引

更新日期：2026-10-23。PR #3–#9 已合并；统一接口与受保护设计见 PR #10。验收范围按用户约束调整。
真机由用户负责，不再阻塞仿真交付。详见 [acceptance-scope.md](acceptance-scope.md)。
阶段证据对应下列固定提交；新增能力以对应工作流结果为准。

| 阶段 | 实际结果 | 范围与剩余项 |
|---|---|---|
| P0 | 原始 CLI、Ruff、unittest/pytest 与 3.10–3.12 矩阵通过 | 基础修复已合并；持续运行 Python 3.10–3.12 回归 |
| P1 | 有限采用范围的 Gate 通过；已完成工程评审 ADR | PathSim 仅开环适配，motulator 已进一步接入；AEL/Mavrith 仍为 reference-only；未覆盖行为逐项列明 |
| P2 | IR v0.1 Gate 通过 | 五种对象、单位/时钟/预算、往返与 native/PathSim 开环适配；非通用方程编辑器 |
| P3 | 单个受控离线提议/失败/修复/验收闭环通过 | 在线 LLM 和任意自然语言规划未验收；没有越过白名单的动态执行 |
| P4 | double 与 float32 PI 内核 SIL 通过 | 当前为 PI 内核；完整 FOC 固件和固定点未覆盖，真机目标时序由用户验收 |
| P5 | PI 内核 SIL、STM32 构建与 ARM QEMU 集成仿真通过 | QEMU 运行 2173 案例；真实设备由用户负责。TI C2000 构建未验证 |
| P6 | 多物理模型、独立参考、合成标定及 FMI RC 验证通过；报告验收见 CI | 交付中文交互 HTML、PDF、PNG/SVG、CSV 与浏览器证据；限定范围见 P6 契约 |

本次改变阶段验收范围，保留原始结果与证据等级；不生成 PIL_measured。
旧报告的 p5_gate_passed=false 对应当时真机 Gate，不代表新版仿真交付被硬件阻塞。

## 已核验的固定运行

- P1：实现提交 5f22af28dc06e278f9d81a7b1320f7b16779efb9，
  [run 39811452404](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39811452404)。
  35 项测试；B0 最大状态误差 4.937e-10；PathSim、motulator、AEL、Mavrith 探针通过。
- P2：提交 865225fb1541963fa6bfddc4b699b71f10604a6f，
  [run 39812297303](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39812297303)。
  39 项测试；跨后端端点最大误差 6.661e-16。
- P3：提交 4b8a157f6ad6ca4fd903c5f5b694038b781c7f5c，
  [run 39812800427](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39812800427)。
  43 项测试；50/s 提议失败，2000/s 修复通过，重复运行 trace hash 一致。
- P4：提交 2135e9ccce9cb31eaa23cfc52cf9da0b7ff40be5，
  [run 39812992108](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39812992108)。
  GCC 15.2；8 手算向量、2000 连续样本、46 异常案例通过；
  最大误差 7.105e-15；编译告警和 -fanalyzer 检查通过。
- P5 准备：提交 d5e2ea97dc8d19d07e1dc574add572185197992f，
  [run 39813265733](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39813265733)。
  ARM GCC 14.2.1，Cortex-M4F hard-float 对象编译成功，函数 .text 1824 字节；
  有未链接的 double/libm 辅助符号，不能当作完整固件大小或实时性能。

每个工作流的 artifact 含输入/输出/版本、源码散列、原始轨迹和日志；
最终运行还生成 outputs/manifest.json。GitHub artifact 有保留期限，长期留档应下载
后按 manifest 校验并移至项目存储。这里没有声称设置了外部存储。

## float32 补充验证

提交 a5b95a79ecea2bf95e96137e8809e7d0511a412d：
[SIL run 39879262200](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39879262200)、
[ARM run 39879262155](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39879262155)。
8 手算向量、2000 连续样本、102 饱和恢复样本和 63 异常案例通过；
最坏误差 1.0785e-5，处于预声明预算内。对象代码段总计 856 字节，
未发现直接双精度依赖；不包含 libm 内部和最终链接开销。

## 用户接手的真机事项

源码、接口与状态更新顺序、共享向量、验证命令、CI 报告和交叉编译产物已提供。
用户自行接入现有固件/HAL、保护链路并完成刷机、上电、PIL/HIL、
目标时间/抖动/栈和最终链接资源验证；这些事项不阻塞 Agent 后续仿真研发。
TI C2000 的确切器件/SDK/工具链按实际可用性补充，不宣称现已验证。

## P6 多物理与报告

数学/模型验证提交 be8f05d76377cfc3a6b501a96e2aee949c2d316d，
[run 39883445674](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39883445674)。
49 项测试通过；全耦合独立 DOP853 末态误差 2.99e-12，热网络参考误差 5.33e-13 K；
独立合成验证 RMSE 0.00477 K，FMI RC 误差 1.39e-13 K。
报告与 UI 以 PR #7 最新 P6 工作流中的 report/ui-validation.json 为验收记录。
[下载与复现指南](p6-report-guide.md) / [模型与固定阈值](p6-model-contract.md)。


## 开源模型深化与统一接口

PR #9 已合并。motulator 固定提交覆盖实际 PWM、死区、二极管续流、母线、
非线性磁图和传感器；MuJoCo / Menagerie 固定 UR5e 模型用于一个电机驱动关节，
其余关节由上游位置执行器保持。六节点热网络支持损耗回放与电阻反馈。

[已核验 run 39905210996](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39905210996)
保留 12 个电气工况与 4 个机器人工况、独立参考、51 项测试及报告浏览器证据。
原始位置 PD 的尾段误差约 0.03756 rad，超过固定目标 0.03 rad；
数值正确不能代替物理目标达成。接触夹具为有初始压入的合成场景，不是实物冲击标定。

PR #10 将五种配置统一到 IR 0.2 / CLI / Agent 工具接口，保留 IR 0.1；
增加原始流单位、资产锁、时钟与预算校验和独立重算验收。
设计流程使用 python-control / Optuna / SALib，训练与 PWM / 齿隙 / 载荷验证分开。
目标、轨迹、限值、预算和模型禁止由优化器修改。具体改善指标以该 PR 的最新
Unified studies and control design 工作流与 report-data.json 为准，不提前声称通过。

尚存的系统性缺口包括完整关节 FMI/OpenModelica 互操作、全系统能量与热源闭合、
完整 FOC C 固件仿真、长时非线性鲁棒验证，以及通用在线 LLM 规划验收。
真机不计入 Agent 交付前置条件。
