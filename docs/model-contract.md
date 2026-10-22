# PMSM dq 模型约定

## 坐标与符号

- 使用转子磁链定向 dq 坐标，采用幅值不变 Park 变换对应的转矩系数 `3/2`。
- `omega_e = pole_pairs * omega_m`，机械角速度正方向与 q 轴正转矩方向一致。
- `vd`、`vq` 是平均定子相电压在 dq 轴上的分量；`load_torque_nm` 是与正转方向相反的负载转矩。
- 电流、磁链、转速、角度均为相应 SI 单位；温度和饱和效应尚未建模。

## 方程

```text
did/dt = (vd - Rs*id + omega_e*Lq*iq) / Ld
diq/dt = (vq - Rs*iq - omega_e*(Ld*id + psi_f)) / Lq
Te     = 3/2 * p * (psi_f*iq + (Ld-Lq)*id*iq)
dwm/dt = (Te - Tload - B*w_m) / J
dtheta/dt = wm
```

## 数值方法

固定名义步长四阶 Runge–Kutta；若 `duration_s` 不是 `step_s` 的整数倍，最后一步缩短，使末样本精确落在仿真终点。输入在整个仿真区间保持常数。

## 有效范围和缺项

这是集中参数、平均电压的刚性转子模型。当前不描述逆变器开关、PWM/ADC 同步、死区、电压限幅、磁饱和、铁耗/铜耗、温度、齿槽转矩、弹性传动或编码器误差。扩展这些效应前，需要为每个新假设加入可独立检查的基准案例。

