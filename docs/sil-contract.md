# P4 C 控制内核与 SIL 契约

范围是 dq PI **状态转移内核**；并非完整 FOC 固件、PWM 驱动或代码生成器。
顺序、单位和零 Ki 语义与 current-controller.md 一致。
参数/输入/状态/输出数组的 ABI 见 firmware/oeal_current_pi.h。
输出不得与输入数组别名；由调用方提供独立缓冲，控制状态只在成功后提交。
错误返回 1 且输出清零；输入和旧状态不变。禁止 -ffast-math。

共享向量在实现前按手算递推定义，见 benchmarks/sil-vectors.json；
固定 abs=1e-11、rel=1e-12，适用于当前宿主 IEEE754 double/libm，
用于检出更新顺序、单位、限幅和状态差异，不适用于 float32 或固定点目标。
先将 Python 和 C 各自与手算向量比较，再逐样本比较长序列，
记录所有 8 个输出、每个向量误差、失败索引及编译器/源码/二进制散列。
NaN/Inf、非正周期、非法状态、溢出单独比较失败行为。
GCC 开启 -std=c11 -Wall -Wextra -Werror -pedantic，另执行 -fanalyzer 静态检查。

尚未实现固定点、float32、Clarke/Park、前馈、SVPWM 的 C 版本。
本 Gate 覆盖指定 double PI 内核，不将其泛化为完整嵌入式 FOC SIL。
STM32G474 的单精度 FPU 不加速 double 运算；目标性能必须实测。
