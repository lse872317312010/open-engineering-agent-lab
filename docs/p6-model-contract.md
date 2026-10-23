# P6 多物理仿真契约与预声明验收

日期：2026-10-23。所有默认参数均为合成研究值，不是实测电机/关节参数。
本轮 Gate 使用仿真、独立参考和合成独立数据集，真机由用户负责。

## 机械域（SI）

双惯量状态 theta_m, omega_m, theta_l, omega_l；减速比 N>0。
传动误差 e(theta_m)=A*sin(theta_m)，限制 A<1/N。
delta=theta_m/N-theta_l-e；a=1/N-A*cos(theta_m)；
delta_dot=a*omega_m-omega_l；Tc=K*delta+D*delta_dot。
Jm*omega_m_dot=Te-a*Tc-Bm*omega_m-Cm*tanh(omega_m/v_eps)；
Jl*omega_l_dot=Tc-Tload-Bl*omega_l-Cl*tanh(omega_l/v_eps)。
机械角速度单位 rad/s、转矩 N*m、刚度 N*m/rad、阻尼 N*m*s/rad。
a*Tc 的写法保留传动误差下的功率一致性。
无摩擦/阻尼/外力时，动能加 0.5*K*delta^2 守恒；
有阻尼/摩擦时相应耗散非负。不实现齿隙接触、塑性或齿面动力学。

## 三节点热网络

节点为绕组 Tw、壳体 Tc、功率板 Tb，单位 degC；
热容 Cw/Cc/Cb 单位 J/K，热阻 Rwc/Rca/Rbc/Rba 单位 K/W。
Cw*Tw_dot=Pw-(Tw-Tc)/Rwc；
Cc*Tc_dot=(Tw-Tc)/Rwc+(Tb-Tc)/Rbc+Pfriction-(Tc-Ta)/Rca；
Cb*Tb_dot=Pb-(Tb-Tc)/Rbc-(Tb-Ta)/Rba。
Rs(Tw)=Rs25*(1+alpha*(Tw-25))；
Pw=1.5*Rs(Tw)*(id^2+iq^2)。
Pb=1.5*Rds*(id^2+iq^2)+E_switch_per_amp*fsw*hypot(id,iq)。
Pb 是透明的平均损耗代理，不是 MOS 结温/开关器件的额定值模型。
能量平衡：各节点储热速率之和=输入功率-流向环境的热功率。

## 电气/逆变器与时序

沿用幅值不变 PMSM dq 方程、静止 alpha/beta 零阶保持和 20 kHz PI。
母线 Vdc(t)=Vdc0*(1+r*sin(2*pi*f*t))，0<=r<0.5。
平均死区/压降误差按各相电流符号的平滑 tanh 近似；
相误差=(Vdc*deadtime*fsw+device_drop)*tanh(i_phase/i_eps)。
去掉零序并裁剪到当前母线线性区；这不是开关级 PWM 模型。
采样→控制计算→可选一周期延迟→保持电压→RK4 子步；
20/120 kHz 排程已有 P1/P5 证据，未模拟真实 ADC 孔径/ISR 抖动。
热阈值事件锁存为“仿真零电压指令”，并清零 PI。
这是可检查的命令停机语义，不是电机断电或硬件保护认证。

## 多时间尺度与数据

短时全耦合实验：电流、双惯量和三节点热同时 RK4 积分，控制按 tick 更新。
长时热实验：指定理想电流包络驱动热网络，不宣称运行了完整 20 kHz 控制。
标定基准：独立单节点 RC 解析式生成训练/验证工况，分别留存；
用离散极点拟合 R/C，验证集不参与拟合。合成数据误差不能当实测偏差。
FMI 适配首版只针对单节点 RC 热模型，完整关节 FMU 与 OpenModelica 未实现。

## 实现前固定的 Gate

- 无损机械能误差<=1e-6 J，耗散测试能量不增加。
- 三节点热网络独立矩阵指数参考误差<=1e-6 K；
  加热/冷却、环境平衡、总能量守恒方程测试通过。
- 全耦合步长减半最大状态差<=2e-4；状态/功率/指标全部有限。
- 独立 DOP853 对同一固定输入的耦合方程末态误差<=2e-5。
- 合成 RC 标定 R/C 相对误差各<=5%，独立验证 RMSE<=0.15 K。
- FMI 2.0 热 FMU 与独立解析式误差<=1e-6 K。
- 不可达电流/温升工况须保留失败结果；不通过修改阈值掩盖失败。
- 报告必须包含参数来源、固定种子、输入/版本/输出 hash、
  限定范围的不确定性扫描、可复现命令及交互界面验证记录。
