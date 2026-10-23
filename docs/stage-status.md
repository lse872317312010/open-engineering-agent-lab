# 阶段状态与证据索引

更新日期：2026-10-23。实现见 PR #3/#4，验收范围按用户最新约束调整。
真机由用户负责，不再阻塞仿真交付。详见 [acceptance-scope.md](acceptance-scope.md)。
以下为该工作分支证据，不能据此宣称 main 已包含或通过这些功能。

| 阶段 | 实际结果 | 范围与剩余项 |
|---|---|---|
| P0 | 原始 CLI、Ruff、unittest/pytest 与 3.10–3.12 矩阵通过 | 主分支原有 import lint 失败在工作分支修复；尚未合并 |
| P1 | 有限采用范围的 Gate 通过；已完成工程评审 ADR | PathSim 仅开环适配，motulator/AEL/Mavrith 为 reference-only；未覆盖行为逐项列明 |
| P2 | IR v0.1 Gate 通过 | 五种对象、单位/时钟/预算、往返与 native/PathSim 开环适配；非通用方程编辑器 |
| P3 | 单个受控离线提议/失败/修复/验收闭环通过 | 在线 LLM 和任意自然语言规划未验收；没有越过白名单的动态执行 |
| P4 | double 与 float32 PI 内核 SIL 通过 | 当前为 PI 内核；完整 FOC 固件和固定点未覆盖，真机目标时序由用户验收 |
| P5 | 当前 PI 内核仿真/SIL 与 STM32G474 构建交接范围通过 | 新版 Gate 不要求真机；用户负责 HAL 集成与板端测试。TI C2000 构建尚未验证 |

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
