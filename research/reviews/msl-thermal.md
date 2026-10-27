# Modelica Standard Library 热组件有限采用

日期：2026-10-27。决策：**adopt**，限六节点线性热网络与一小时FMI交换验证。
本轮采用真实MSL组件方程和物理连接器，不将编译器采用等同物理模型采用。

## 上游与许可证
ModelicaStandardLibrary v4.0.0标签对象f1138440e53ccfe3ab203fe584718f1081667dd6，
解析到提交6626538a236a34a390655b55d5e8c906bfe31772。
[上游许可证](https://github.com/modelica/ModelicaStandardLibrary/blob/6626538a236a34a390655b55d5e8c906bfe31772/LICENSE)
为BSD3-Clause；完整原文归档[MSL-4.0.0.txt](../licenses/MSL-4.0.0.txt)并随FMU分发。
构建核对源checkout提交、无修改状态、许可证字节一致以及实际使用源文件散列。

使用HeatCapacitor×6、ThermalResistor×7、PrescribedHeatFlow×6、FixedTemperature×1；
实际加载Complex、ModelicaServices及Modelica的同一固定源码，
用编译器getVersion/getComponents和真实FMU导出确认采用，不仅引用README。
原创连接模型和固定热容/热阻/热源参数仍为OEAL合成研究资产。

## 数值、互操作和证据
内部K、输出摄氏度；六个保持功率输入，环境温度初始化前固定。
FMI2 ModelExchange由FMPy导入；主机DOP853逐通信窗推进，无事件。
独立Radau物理端口方程与原生矩阵指数逐点比较；
六组一小时、两种通信周期、完整能量账与热流审计见阶段状态。
固定契约/手算参考先于模型实现，原七IR配置及可信资产名单不改。

FMU保留生成源码/版权，另外提供MSL许可证、实际使用组件源码、
连接源码、固定契约、编译器版权/使用模式及库/镜像实际来源。
本轮只验收Linux x86_64；没有证明通用FMU事件处理、硬实时或物理温度精度。

## 未覆盖
未引入温度相关热阻热容、非线性对流/辐射、空间有限元、冷却流体或封装标定。
没有把这次预设损耗回放称为一小时电机/PWM/机器人联合仿真。
器件温度额定值和实物散热能力不由数值一致性Gate证明。
后续应先接入真实仿真损耗端口并冻结跨域时钟/热反馈，再扩展参数与模型保真度。
