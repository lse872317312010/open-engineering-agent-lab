# 阶段状态与证据索引

记录日期：2026-10-22。工作分支 codex/roadmap-p1-p5，PR #3。
以下为该工作分支证据，不能据此宣称 main 已包含或通过这些功能。

| 阶段 | 实际结果 | 范围与剩余项 |
|---|---|---|
| P0 | 原始 CLI、Ruff、unittest/pytest 与 3.10–3.12 矩阵通过 | 主分支原有 import lint 失败在工作分支修复；尚未合并 |
| P1 | 有限采用范围的 Gate 通过；已完成工程评审 ADR | PathSim 仅开环适配，motulator/AEL/Mavrith 为 reference-only；未覆盖行为逐项列明 |
| P2 | IR v0.1 Gate 通过 | 五种对象、单位/时钟/预算、往返与 native/PathSim 开环适配；非通用方程编辑器 |
| P3 | 单个受控离线提议/失败/修复/验收闭环通过 | 在线 LLM 和任意自然语言规划未验收；没有越过白名单的动态执行 |
| P4 | double PI 控制状态内核 SIL Gate 通过 | 非完整 FOC 固件；float32、固定点、目标时序尚未验收 |
| P5 | STM32G474 对象交叉编译通过，部署准备已建立 | **P5 Gate 未通过**：无板端 PIL、执行时间、抖动、栈和最终链接资源日志；TI 工具链/工程缺失 |

后续阶段的离线准备不改变其 Gate 状态。没有硬件证据不标记 PIL_measured。

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

## P5 下一步的实际输入

提供 STM32G474 板卡版本、当前固件仓库/分支、实际时钟/SDK/编译配置；
按 p5-deployment-contract.md 接入现有 HAL 和保护链路。
真实刷机/上电另行授权后才可采集原始 PIL/cycle/jitter/stack/link-map 日志。
TI C2000 还需要确切器件、SDK 与已许可的工具链。
在这些资料与运行能力缺失时，P5 Gate 保持 blocked，不生成替代实测数据。
