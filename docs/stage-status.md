# 阶段状态与证据索引

更新日期：2026-10-24。PR #3–#11 已合并；统一接口与受保护设计见 PR #10，架构见 PR #11。验收范围按用户约束调整。
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


## 受保护设计的固定验证结果

[run 39913971109](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39913971109)
验证代码提交 c20d066c83508d9068d7b18289eea2a88ed43d5c。
五个配置共用 IR / CLI / Agent 入口；同参数原生与 motulator 平均模型电流差
2.98e-13 A。统一接口数值检查通过，Baldor 电流跟踪目标未达的结果原样保留。

固定种子下进行 8 次平均模型训练。选定 Kp=779.26668 N*m/rad、
Kd=56.60807 N*m*s/rad；这是有限搜索的最佳提议，不是全局最优声明。
以下均重新运行 PWM、死区和器件压降模型；固定位置目标为 0.03 rad：

| 验证工况 | 原始尾段平均绝对误差 rad | 优化后 rad | 固定位置/电流/转矩目标 |
|---|---:|---:|---|
| 原始负载 | 0.0375990 | 0.00399833 | 全部通过 |
| 0.001 rad 齿隙 | 0.0375947 | 0.00435909 | 全部通过 |
| 额外 0.5 kg 载荷留出 | 0.0390057 | 0.00340107 | 全部通过 |

原始负载位置误差改善 89.37%；电流峰值由 1.433 A 升至 2.694 A，
轴转矩峰值由 37.87 N*m 升至 52.93 N*m，均未超过固定 20 A / 100 N*m。
这里的电流峰值同时检查控制采样与求解波形；不是只看指令限幅。
载荷变化的单一留出结果不代表广义鲁棒性证明。

交付报告含 10 组 PNG/SVG、PDF、搜索与验证对比、时间状态回放和 CSV 导出。
Chrome / Playwright 检查离线运行、390 px 布局、键盘游标与导出通过，
无页面错误或外部网络请求。完整证据仍以对应 artifact / manifest 为准。


## 本轮：实际能量端口与机器人接口审计

实现前先提交[能量契约](energy-accounting-contract.md)，再增加手算磁能/器件功率、
独立增广矩阵指数热参考与实际电容 RHS / 机械摩擦端口检查。

首次科学验证：[run 40055075076](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40055075076)，
代码 92a793d5b7e9b19f52f651157e88d4b39d3fbfa3；
64 项测试通过、2 项可选控制库测试因环境未装对应库跳过。
8 组能量实验通过固定局部门槛；全段最大局部余额约 9.65e-11 J。
报告新交互的验收以本分支后续 Energy-port 工作流为准，首轮仅验证原报告交互。

- 平均、PWM、死区/阈值、电容母线、回馈，以及三种 UR5e 宏步均已实际运行。
- 回馈工况源端口净能量 -0.4680 J，保留真实负功率和有符号机械负载功。
- 200 / 100 / 50 μs 宏步的接口余额峰值分别约
  0.003934 / 0.001959 / 0.000978 J，观测到接近一阶缩小；
  这是诊断结果，不把它们冒充热耗散或全局闭合。
- 显式“漏记器件直流耗能”的账本故障注入被局部余额检测为失败，
  原始物理实验与注入副本分开保留。
- `energy_consistent` 默认关闭；新模式的线性电驱局部门槛不覆盖非线性磁图、
  铁损支路、整流前端、夹具接触或完整机器人能量守恒。

完整控制/Agent 设计环境的全部可选测试见下方最终记录；硬件继续由用户负责。

新增能量交互首轮浏览器验收：
[run 40055429768](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40055429768)，
代码 7ca8f6290962d4147352ea8d430437813f44e140。
能量专用报告为 7 组图表（原 P6 五组 + 能量两组），通过故障注入状态、
机器人曲线、0/60 ms 键盘首末点、能量 CSV 与 390 px 布局检查；无页面错误和外部请求。
完整设计工作流同时包含开源深化、原控制优化及能量审计时，报告为 12 组图表。

能量端口实验的机器人轨迹为 40 ms / +0.008 rad；
原有控制设计的 250 ms / +0.08 rad、0.03 rad 目标与限值保持独立回归。

### 最终完整验证

[run 40056246982](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40056246982)，
实现代码 a80aba8ccc543d5903b7036a85b6230c09be99b3；**66 项测试全部通过，无跳过**。
原控制优化保持 89.37% 基准误差改善，三组开关模型验证通过；
新增八组局部能量与故障注入检测通过，原开源模型和五配置统一入口回归通过。

完整报告为 **12 组 PNG/SVG + PDF + 离线交互 HTML**；
[报告包](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40056246982/artifacts/12544699780)
与
[全部证据](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40056246982/artifacts/12544999265)
分开交付。Chrome 检查全部新旧交互、失败状态、时间首末点、CSV、
390 px 布局与参数展示通过，无页面错误或外部请求。
每组能量结果含实际热容/导热矩阵、转子惯量、母线电容与损耗参数。

实现与审计见 [PR #12](https://github.com/lse872317312010/open-engineering-agent-lab/pull/12)。
后续仍需改进机器人联合仿真的接口余额，并扩展长时多工况及完整关节 FMI；
局部数值余额不是用户设备参数误差或真机精度结论。
