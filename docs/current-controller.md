# 离散 dq PI 电流环

这是独立的标量控制器基础模块 `oeal.current_control`，尚未接入仿真 CLI。
d/q 方向沿用 PMSM 模型。电流为 A，电压为 V，周期为 s。

## 方程与更新顺序

在 t[k] 同时采样 id/iq，读取同一时刻的电流指令和外部前馈电压。
先将指令矢量沿径向限制到 Imax，再计算误差。两个轴可使用不同增益：

```text
r = radial_limit(current_reference, Imax)
e = r - measured_current
z_trial = z[k] + Ki * Ts * e
u_raw = Kp * e + z_trial + feedforward
u = radial_limit(u_raw, Vmax)
beta = 1 - exp(-tracking_rate_per_s * Ts)
z[k+1] = z_trial + beta * (u - u_raw)
```

返回的电压 u 应在 [t[k], t[k+1]) 零阶保持；同一步只调用一次控制更新。
积分器采用后向矩形误差更新，再对**包含前馈的总电压**实施回算。
Kp 单位 V/A，Ki 单位 V/(A*s)，tracking_rate 单位 1/s。
beta 在 (0,1] 内，控制回算离散系数；这不保证任意采样周期下的闭环稳定性。
零 Ki 明确表示该轴不使用积分和回算，初始积分也必须为零。

Vmax 是显式配置的 dq 矢量幅值上限，不是直流母线电压；理想线性 SVPWM 下可取 Vdc/sqrt(3)，
但本模块尚未实现 SVPWM、占空比、反电势或解耦前馈计算。外部前馈默认零。
Imax 只限制指令，不能约束真实电流瞬态。测量值不裁剪。

## 状态与校验

参数、积分状态、输出均为不可变 dataclass；`current_control_step` 无副作用，
失败时不会部分更新旧状态。首次调用使用 `CurrentPIState()`；复位可重新创建零状态。
输入、积分、参数和运算结果必须有限，增益非负，周期、限制和回算速率严格为正。
不接受非零积分但 Ki 为零的配置；数值溢出会抛出 ValueError。

## 独立验证

测试使用手算的积分递推、3-4-5 几何限幅、包含前馈的回算值、不同轴增益、
长期饱和后撤销指令恢复以及独立的解析 RL 零阶保持对象。
RL 对象使用精确指数解而非 PMSM/RK4 实现；它只验证静止、解耦单轴基准。
这里的增益是人工构造测试值，不是实际电机整定值。

下一步：实现解耦/反电势补偿、平均 SVPWM，再将明确的采样/控制时序接入闭环仿真。
