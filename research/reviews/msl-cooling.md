# MSL 对流与辐射组件有限采用

日期：2026-10-27。决策：adopt，限六节点独立热FMU的非线性边界及一小时预设热回放。
沿用MSL4.0.0固定提交6626538a236a34a390655b55d5e8c906bfe31772与BSD3-Clause；
不是仅阅读文档或重写同一方程冒充组件复用。

实际使用[Convection](https://github.com/modelica/ModelicaStandardLibrary/blob/6626538a236a34a390655b55d5e8c906bfe31772/Modelica/Thermal/HeatTransfer/Components/Convection.mo)、
[BodyRadiation](https://github.com/modelica/ModelicaStandardLibrary/blob/6626538a236a34a390655b55d5e8c906bfe31772/Modelica/Thermal/HeatTransfer/Components/BodyRadiation.mo)与同版本Constants。
Convection为Gc·温差，BodyRadiation为Gr·sigma·绝对温度四次方差；
本轮Gc外部输入、Gr合成有效面积，未引入流场、风速或表面几何标定。

源散列分别为d4ef0b38dd0e32a794f280e59bae0cbd8debe2d432289526dff14eaebd289402、
96270db8851addbcc084d111d452da1847aa0535524f4b0fa29159fec0dc5ba4、
0394e18394d4e0b6535e309749f12df377c99a42a769f0d7c2e256c734a6ba87；
源文件、许可证与生成运行时版权随FMU保留。
固定编译器/镜像、getComponents、实际导出/导入与全部六组结果见阶段状态。

独立参考先提交，原温度/能量门槛没有依照运行结果修改。
验证关闭辐射的线性极限、Kelvin/Celsius单位陷阱、负流符号、
弱化/恢复Gc、冷热环境与全共同点细步；原七IR及旧FMU不改。
当前是预设损耗的一小时热模拟；实际电驱非线性联合接入和整机耐久仍未验收。
