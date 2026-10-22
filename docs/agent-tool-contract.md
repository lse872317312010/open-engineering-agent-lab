# P3 受限研发闭环契约

受保护目标是 examples/ir/foc-experiment.json 的全部模型、时钟、参考与预算；
唯一可提议字段为 bandwidth_per_s 和 tracking_rate_per_s，范围 (0,5000]。
验收器只读取原始 samples 重算指标，忽略可伪造的 result.metrics。
固定阈值仍为 P1 在实验前声明的 b1_passes，不允许工具调用设置阈值或电流目标。

工具：inspect_model、propose_change、run_experiment、compare_results、
verify_change、record_evidence。只接受 JSON/标量，不接受路径、代码、动态导入、
shell、编译器参数或目标设备。对 native FOC 接口提供固定功能，不开放任意 Python。
这些是应用权限边界，不是能隔离恶意本地 Python 进程的 OS 沙箱。

每个输入/结果/验收/trace 都规范序列化并按 SHA-256 存为账本文件；
写入使用排他创建，不覆盖已有对象。记录 proposal → run → independent verification →
failure diagnosis → repair → verification。当前证据等级只能生成 model_simulated。

首个用例由本次实施助手提出：先试 50/s（预期调节过慢），若固定目标失败，
根据 2%调节时间约 ln(50)/bandwidth 估计选 2000/s，再独立验收。
该离线策略是可复现的工具协议/Agent trace 回归，不宣称测试过某家在线 LLM 或
任意自然语言自主规划。LLM 可替换，通过同一白名单 API 提议变更。
连续两次运行必须得到相同 proposal、raw sample 与验证结果散列。
