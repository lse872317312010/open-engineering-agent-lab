# OpenModelica 关节模型交换契约（实现前冻结）

日期：2026-10-27。推进路线图队列4的外部编译器互操作，不改变七配置或现有白名单。
先固定本契约和独立参考，再实现 Modelica 模型和导出/加载程序。

## 范围与方程
采用 joint-fmi-contract.md 的固定九物理状态、三能量积分、四输入及 SI 方程；
温度输出仍为摄氏度，热容储能相对25°C，dq输入按通信窗零阶保持。
模型由本项目原创 Modelica 方程表达，经真实 OpenModelica 导出 FMI2 ModelExchange，
FMPy 加载生成二进制，主机按每个通信窗用 SciPy DOP853 积分。
与现有独立 joint_fmi_reference.py 和原创 C CoSimulation FMU 三方对照。
这是同方程跨实现/工具交换验证，不是外部实测模型或新增物理精度。
ModelExchange 的积分器由主机提供；不得声称生成FMU内含独立CS求解器。

模型：R=.3*(1+.00393*(Tw-25)), we=7*wm；
did=(vd-R*id+we*.0008*iq)/.0008；
diq=(vq-R*iq-we*(.0008*id+.03))/.0008；
Tshaft=80*(tm/10-tl)+.15*(wm/10-wl)；
dwm=(.315*iq-Tshaft/10-1e-5*wm)/5e-5；
dwl=(Tshaft-load-.02*wl)/.02；dtm=wm，dtl=wl。
Pcu=1.5*R*(id²+iq²)，Pf=1e-5*wm²+.02*wl²+.15*(wm/10-wl)²；
Qwc=(Tw-Tc)/.8，Qbc=(Tb-Tc)/1.2，Qca=(Tc-25)/2，Qba=(Tb-25)/4；
dTw=(Pcu-Qwc)/60，dTc=(Qwc+Qbc+Pf-Qca)/200，dTb=(board-Qbc-Qba)/25。
dEin=1.5*(vd*id+vq*iq)+board，dEload=load*wl，dEambient=Qca+Qba。
储能/余额采用独立参考，不能采用FMU自报余额替代重算。

## 固定实验和门槛
直接复用原四组0.08s输入 no-load / loaded-heating / reversal / variable-clock；
1601通信端点，50us或交替25/75us，不能插值抹平输入跳变。
全部12输出与独立参考逐项误差<=2e-5（各自SI单位），
九物理状态与原C FMU逐项误差<=2e-5；实际输出重算能量余额<=2e-6J。
FMI元数据必须ModelExchange、12连续状态、四Real输入、13Real输出（含轴转矩）；
按变量名解析valueReference，不假定Modelica编译器状态顺序。
轴转矩按真实状态独立重算，误差<=2e-5 N*m。
所有端点有限、时间严格递增、零初态/25°C初始化正确。
零激励平衡、纯板热初始导数1K/s（25W）、
静止d轴1V初始导数1250A/s、独立实例和reset重现另行检查。
将输入能量副本添加1mJ必须被独立余额门槛拒绝。
不复用旧C的GUID/二进制白名单，不在运行时接受任意外部FMU路径。

## 来源、证据与交付
OpenModelica固定v1.25.5，官方标签源码38bef66da59e57597a6a5f482695e6c37ca09940；
官方minimal Docker镜像先解析并记录实际RepoDigest，再按同一摘要运行、记录omc --version。
不使用latest，不宣称标签等于不可变摘要。FMPy0.3.26/SciPy1.15.3。
编译器作为独立工具使用，OSMC许可证选AGPL模式；原创Modelica源码MIT。
不复制编译器实现；生成FMU运行时代码保留原始许可/版权及生成源码，
归档镜像包版权、编译日志、Modelica源码、FMU、元数据、全量CSV、独立参考与散列。
许可证来源 https://github.com/OpenModelica/OpenModelica/blob/v1.25.5/OSMC-License.txt；
运行时头文件包含BSD NEW/GPL3/OSMC可选声明，选择BSD并保留随包通知。
若实际包声明不相容或缺少运行时通知则不发布该二进制。

必须真实执行导出与导入，Ruff/pytest与报告浏览器检查通过才能声明完成。
报告包含三方曲线/误差/能量、组件及求解器机制、工况和时间回放、全量CSV及适用边界。
只在仿真环境验收；真机由用户负责。
