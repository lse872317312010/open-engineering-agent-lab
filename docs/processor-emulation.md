# ARM 处理器集成仿真（PIL-style）

用户允许在 ARM 或 RISC-V 仿真环境完成处理器集成验证，本次选择 ARM QEMU，
以复用现有 Cortex-M4F float32 PI 内核。此后端作为仿真验收的一部分。

## 运行契约

- QEMU machine=mps2-an386，CPU Cortex-M4；这是虚拟 MPS2 平台，不是 STM32G474 外设模型。
- 使用 ARM GCC 交叉编译并实际链接 bare-metal ELF、libm/newlib，
  自定义向量表、数据/BSS 初始化和 FPU 使能，QEMU 执行 ARM 指令。
- semihosting 仅在 CI 受控 QEMU 中启用，用于向主机输出测试行和退出；
  不读取宿主文件、不接受外部命令，也不用于用户的真实设备。
- 输入以 binary32 位模式生成，包含共享手算向量、状态连续序列与非有限值。
- ARM 端只执行控制器并输出返回码和 8 个原始 float 位模式。
  宿主独立对照手算和 Python double 参考，不在目标中嵌入预期输出。
- 延用 float32 预声明 abs=2e-4、rel=2e-5，布尔标志与错误码精确比较。
  丢行、重复行、错误次序、FAULT、超时和非零退出均判为失败。
- 保存 ELF/map/size、生成的输入头文件/位模式、原始 stdout/stderr、
  全部逐样本误差、命令、QEMU/编译器版本和产物散列。

## 证据标记

报告 evidence_kind=processor_emulated；成功时标记 processor_validation_passed。
不使用 PIL_measured：QEMU 墙钟时间不代表芯片执行周期/WCET，
链接资源仅属于该测试 ELF。真实 STM32 HAL/外设、ADC/PWM、
中断抖动与电机行为不在本用例内。真机由用户负责，不阻塞仿真验收。
