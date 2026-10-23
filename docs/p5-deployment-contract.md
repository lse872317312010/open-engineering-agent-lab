# P5 仿真交付与用户真机交接契约

依据 2026-10-23 用户约束：Agent 以仿真/SIL 达标与可复现交接包完成本阶段，
真机工作由用户自行实施，不是 Agent Gate 的前置条件。
详见 [acceptance-scope.md](acceptance-scope.md)。目标顺序为 STM32G474，再 TI C2000。

## Agent 仿真交付产物

- 纯 C 控制状态转移函数，不包含 HAL、寄存器操作、ADC/PWM 启动或刷机逻辑。
- 主机 SIL：同输入/状态下比较 Python 与 C；编译器版本、源码 hash、
  每向量误差和声明容差全部留存。
- STM32 编译探针：`arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb
  -mfpu=fpv4-sp-d16 -mfloat-abi=hard`。对象文件的 size/disassembly 是交叉编译证据，
  不等于可启动固件、最终链接 Flash/RAM、栈用量或板端执行时间。
- TI C2000：需要目标器件、可用 SDK/编译器版本及现有工程；无这些信息不虚构构建结果。

## 用户接手：与现有固件的集成点

保留原有 HAL、ADC/PWM/DMA/编码器、故障关断和保护链路。
控制 tick 只传入已校准采样与本周期参数，获取受限电压指令。
母线/电流/温度异常仍由现有保护链路处理；研究控制器不替代保护。
双精度主机 SIL 通过后，必须对目标浮点精度和 libm 再做误差预算，
Cortex-M4F 对 double 没有同等硬件支持，不能据主机时间声明满足 50 us。

## 用户真机验收可参考的板端记录（不阻塞 Agent 交付）

```json
{
  "evidence_level": "PIL_measured",
  "target": "STM32G474",
  "board_revision": "<actual>",
  "firmware_commit": "<actual git SHA>",
  "toolchain": "<actual version and flags>",
  "clock_hz": 170000000,
  "control_period_us": 50,
  "sample_count": 100000,
  "max_observed_cycles": "<measured integer>",
  "interrupt_jitter_cycles": "<measured>",
  "flash_bytes": "<linked map>",
  "ram_bytes": "<linked map>",
  "stack_peak_bytes": "<measured or bounded>",
  "error_count": "<measured>",
  "raw_log_sha256": "<actual>",
  "authorization_reference": "<separate hardware action authorization>"
}
```

上面全部为格式示例，数值/占位不能作为证据。时钟必须按实际板配置确认。
PIL 使用固定测试向量，经 UART/SWD 等已授权通道回传实际结果；
记录计时器/DWT 溢出、测量开销、预热、优化选项和干扰负载。
报告 **最大观测时间**；无静态分析或保守论证不使用 WCET 表述。
实际运行结果必须关联原始日志散列，不能从主机 SIL 或 ELF size 推导。
刷机、上电及电机运行依照总路线图要求单独授权，当前工作不操作硬件。
