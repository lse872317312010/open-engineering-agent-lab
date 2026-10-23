# P2 IR v0.1

单一 JSON Schema：src/oeal/schemas/ir-0.1.json，随 Python wheel 打包。
五个对象均具 kind/version，严格拒绝未知字段。
ModelSpec 仅注册 pmsm_dq_v1，参数含 value/unit、显式端口和 control/PWM 时钟；
ExperimentSpec 引用完整模型，固定输入、求解设置、seed=0 和步数预算。
SimulationResult 包含信号列名（SI 单位按后缀）、时间样本、独立指标和输入散列。
CodeArtifact 记录目标/ABI/编译器/flags/源码及二进制和资源报告 hash；
Evidence 记录等级、命令、环境、结果和不可变产物 hash。

运行时额外检查单位、整数多速率关系、控制 tick 对齐、有限数值、预算与结果形状。
v0.1 使用确定性白名单，无表达式、import、shell 或外部 schema URL 解析。
所有 schema 引用只来自内置文件；不是通用代码执行框架。

native 支持 FOC/open_loop；PathSim 可选支持 open_loop，输出端点以避免隐式采样语义差异。
open_loop 两个后端采用同一 ModelSpec/ExperimentSpec，只切换 backend；
FOC 的采样为 control_ticks_and_endpoint。每类结果显式标明 sample_semantics。
控制设置字段通过名称及固定 schema 声明 SI；不接受隐含 mH/ms 转换。

依赖 jsonschema 的根许可证 MIT 已核查；它是 schema 验证器，不作为模型求解器。
