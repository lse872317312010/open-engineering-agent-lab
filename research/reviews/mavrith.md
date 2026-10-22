# mavrith 评审

- 上游：https://github.com/Yuzhe-Xu/Mavrith
- 评测日期：2026-10-22；固定提交：`718e64e24cfb2e40ebaec8a9c94bf56c121e041b`。
- 根许可证：MIT；已读取该提交的许可证文本与 pyproject.toml。
- 决策：**reference-only**。借鉴信号端口类型；当前仅探测类型接口，不足以采用其求解与多速率运行时。
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

安装并创建 float 二维 SignalSpec/PortSpec；Python>=3.11。
尚未覆盖编译模型、采样率传播、状态复位、错误拓扑及求解精度。
仅凭端口探针不通过“采用运行时”的门槛；后续需独立评测后再更改决策。
