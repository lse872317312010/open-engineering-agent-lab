# OpenModelica 受限采用记录

日期：2026-10-27。决策：**adopt（固定植物的 FMI2 ModelExchange 编译/导入验证）**。
不把工具链采用写成成熟整机模型、MSL组件库或全部FMI功能已采用。

## 可重复实验
官方源码标签v1.25.5解析到38bef66da59e57597a6a5f482695e6c37ca09940。
实际编译器报告OpenModelica 1.25.5，官方minimal镜像解析后固定：
openmodelica/openmodelica@sha256:116ec5a9404019c8cee3111ad80e0db7f09ad7bc433c3777feb05b2418d5e57d。
[官方Docker说明](https://openmodelica.org/download/docker/)说明minimal提供命令行omc，
不附带Modelica库；本轮原创纯方程模型不加载或安装MSL。

执行build_openmodelica.py -> validate_openmodelica.py -> build_openmodelica_report.py。
经真实编译生成的12连续状态ME FMU由FMPy0.3.26导入；
按变量名解析端口，主机DOP853按真实通信窗ZOH推进，独立Python方程和
原C CoSimulation/RK4为对照；实际结果、逐项误差和下载见阶段状态。

## 许可和可替换性
原始[OSMC-PL1.8](../licenses/OpenModelica-v1.25.5.txt)已核验，
独立编译工具使用AGPL3模式，未将编译器实现复制到项目运行时。
运行时源头文件具有BSD NEW/GPL3/OSMC可选声明；
BSD声明及其他第三方原始版权保留在生成sources/，包版权完整归档。
FMU额外resources/oeal-licenses/提供原创MIT许可、模型源码、固定契约、
OSMC原文、使用模式和实际编译器包版权，原始生成源码不删改。

原创Modelica源码保留MIT；FMU与编译器是可替换工具产物。
本轮未向统一IR注册新配置或修改既有可信资产白名单；
不允许实验JSON自行指定动态库或新二进制散列。
FMU只覆盖Linux x86_64，不据此宣称Windows/ARM兼容。

## 尚未采用
MSL电机/机械/热组件、外部经过标定的Modelica模型、OpenModelica CS求解器、
多FMU强耦合、保护事件、控制器交换和完整MuJoCo机器人封装均未在本轮验收。
当前ME主机只接受该无事件ODE；不是支持任意FMU的通用事件驱动主机。
四组短时实验验证方程与工具交换一致性；不能推导长期、全参数域或实物精度。

## 后续采用状态

2026-10-27，[PR #22](https://github.com/lse872317312010/open-engineering-agent-lab/pull/22)
已继续有限采用MSL4.0.0热组件并验证六节点热FMU，见[独立采用记录](msl-thermal.md)。
上文“尚未采用MSL”描述PR #21时的范围；其余事件/控制器/整机未覆盖项仍保留。
