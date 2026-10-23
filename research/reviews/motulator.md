# motulator 评审

- 上游：https://github.com/Aalto-Electric-Drives/motulator
- 评测日期：2026-10-22；固定提交：`2ffbf1ae52d5fadcdffd85d10c80dd15fd2e39fa`。
- 根许可证：MIT；已读取该提交的许可证文本与 pyproject.toml。
- 决策：**reference-only**。复核电机方程和 RL 极限；不将其控制栈作为独立真值，也不把 Python>=3.12 引入核心。
- 复现：Python 3.12、Ubuntu GitHub hosted runner；
  `pip install -r benchmarks/requirements.txt && pip install -e ".[dev]"`，
  `python benchmarks/validate_p1.py`。固定上游源码提交，不复制其源码。
- 具体 OS/CPU、运行版本和传递依赖锁定记录：CI 产物
  `p1-evidence/p1/environment.json`、`pip-freeze.txt`；
  完整安装/运行日志见 PR #3 的 P1 evidence Actions。
- 运行时长与峰值 RSS：同一评测进程的 run.json；不是可用于候选排序的隔离性能实验，
  不能解释成 MCU 时间或内存。
- 第三方依赖按 pyproject 声明安装，实际版本由 freeze 留存；未作全量 SBOM/所有可选插件审计。
  MIT 要求保留许可/版权，Apache-2.0 须保留许可/NOTICE 等适用声明；
  此次不重新分发上游源码，也不将实验依赖加入 OEAL 核心。
- API 是可信 Python 代码，**不是沙箱**。不允许由 JSON 指定 import、回调源码、shell 或任意后端类。
  本轮只运行仓库中固定的探针，不接受用户动态可执行模型。
- 开放输出：探针导出 JSON；未采用候选专有模型文件作为唯一事实源。
- 原始测量与通过/失败：对应的 pathsim.json / motulator.json / interfaces.json。
  报告不以 README 的功能宣称替代运行证据。

## 已覆盖与未覆盖

运行 SynchronousMachine 的电流/转矩和 RHS：零速、正速、反转、凸极参数；
以实际机器 RHS 积分并对比独立 RL 指数解。Python>=3.12 与核心基线不一致。
未运行其完整控制器/变换器/机械联仿，多速率/延迟、复位、非线性模型不在本轮证据范围。
因此保持领域参考，不能声称完整 B1 跨后端等价。
