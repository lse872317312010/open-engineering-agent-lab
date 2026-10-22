# ADR 0001：原生参考模型和可选 PathSim 适配

日期：2026-10-22。状态：本次实施助手完成工程评审并接受；尚无外部维护者审批。
适用范围：当前平均电压 PMSM/B0/B1。

## 固定证据

提交 5f22af28dc06e278f9d81a7b1320f7b16779efb9 的
[P1 evidence](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/39811452404)
通过：35 项测试、pytest、Ruff、原始 CLI、独立 B0/B1 和全部候选探针。

- B0 步长 4e-5/2e-5/1e-5 s，独立 DOP853 最大状态误差
  1.268e-7 / 7.900e-9 / 4.937e-10。
- PathSim B0 末态差 3.55e-15，复位误差 0，1 ms 内排程 20/120 个 tick。
- motulator 方程与转矩误差 2.22e-15，独立 RL 解析误差 2.66e-11 A。
- AEL 安装并导出 21 项 schema；Mavrith typed-port 探针通过。
- B1 零/正/负速、参数偏差和一周期延迟通过。
  标称稳态误差 1.291e-4 A，2%调节时间 1.9 ms，电压约束违反 0。
- 1 V 母线案例按预期验收失败。总评测耗时 4.26 s、累计峰值 RSS 159556 KiB，
  不是候选隔离性能排名，不是 MCU 证据。

固定上游提交、许可证、安装记录、未覆盖行为见 research/reviews 和 CI artifact。

## 决策与评审范围

1. 原生模型保留为可读规范和确定性参考，独立数学参考不依赖原生 RHS。
2. PathSim 为可选 adapt 后端；不以它的内部文件格式拥有工程资产。
3. motulator 为 reference-only，不用另一控制库作为验证真值。
4. AEL/Mavrith 为契约和端口参考，不接入其 worker 或扩张执行权限。
5. IR 采用版本化 JSON Schema、显式 SI 单位和固定后端注册。
6. 核心维持 Python 3.10–3.12；研究环境独立 Python 3.12。

评审核查许可、固定版本、运行日志、独立参考、失败案例与边界。
零交叉、代数环、完整 motulator 控制栈和 Mavrith 调度尚未验收，
均未作为采用范围。AEL 只验证 schema API。
基于上述有限决策与运行证据，P1 Gate 通过，可进入 P2。
外部维护者可在 PR #3 审查中修订本决策。

P2 最小对象为 ModelSpec、ExperimentSpec、SimulationResult、CodeArtifact、Evidence；
禁止 JSON 指定 import/shell/可执行方程。jsonschema 根许可 MIT 已核查，
使用其验证器，避免自写 JSON Schema 引擎。
