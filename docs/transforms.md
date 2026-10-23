# Clarke/Park 坐标变换

阶段 1 的第一项基础实现位于 `oeal.transforms`，只提供纯函数，不修改电机状态。

## 方程、单位与符号

采用 abc 正相序和幅值不变约定。输入可以是电流或电压，输出保持相同单位。
角度必须是电角度（rad）：`theta_e = pole_pairs * theta_m`，不可直接传入机械角度。

```text
alpha = (2*a - b - c) / 3
beta  = (b - c) / sqrt(3)
zero  = (a + b + c) / 3
d =  alpha*cos(theta_e) + beta*sin(theta_e)
q = -alpha*sin(theta_e) + beta*cos(theta_e)

alpha = d*cos(theta_e) - q*sin(theta_e)
beta  = d*sin(theta_e) + q*cos(theta_e)
a = alpha + zero
b = -alpha/2 + sqrt(3)*beta/2 + zero
c = -alpha/2 - sqrt(3)*beta/2 + zero
```

当三相为 `A*cos(theta_e + [0, -2*pi/3, 2*pi/3])` 时，得到 `d=A, q=0`。
该 q 轴方向与现有 PMSM 方程及正 q 轴电流产生正永磁转矩的约定一致。

零序作为独立分量保留；Park 变换只处理 alpha/beta。逆 Clarke 的零序默认值为 0。
瞬时功率满足 `sum(v_phase*i_phase) = 3/2*(vd*id + vq*iq) + 3*v0*i0`，
因此不能将该变换当作功率不变归一化。现有三线 PMSM 模型不模拟零序动力学。

## 验证与边界

测试使用已知相轴、解析平衡正弦、正 q 轴方向、非平衡零序往返、旋转范数与瞬时功率恒等式，
并检查每个参数位置的 NaN/无穷输入。测试向量使用无量纲数值，恒等式同样适用于 SI 电流/电压。
这些是坐标变换基准，不代表已经完成闭环控制或硬件验证。

接口当前为标量，不接受数组；不提供编码器校准、角度估计、控制更新时序或逆变器模型。
下一步为离散 PI 电流环、矢量限幅和抗积分饱和，随后接入解耦补偿及平均 SVPWM。
