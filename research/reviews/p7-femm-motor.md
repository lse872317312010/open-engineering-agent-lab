# FEMM真实永磁电机候选采用

决策adapt，仅独立Windows研究环境。
FEMM4.2 21Apr2019官方DokuWiki分发端点，安装包SHA256：
17384e8990b6305ec8ffef1f75b6ef091a266b6e49b30c151cd1daca2e952043；
实际运行femm.exe SHA256：
5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21。
两者均在安装/运行前校验；后者来自成功圆柱探针41400947522。
pyfemm0.1.3通过COM驱动真实预处理器、Triangle网格与FEMM磁场求解器，
无自写静磁FE替代或预制磁链结果。

许可：FEMM/pyfemm为AFPL，包含有特定分发限制的Triangle及Lua。
不标记为MIT/BSD或无条件可商业分发的OSI组件。
原AFPL第2(b)指出功能运行不受该许可限制，
但程序复制/修改/付费捆绑分发有另外条件；本次只运行独立安装，不重分发安装包/exe/DLL。
归档原创fem输入/ans解/数值输出和完整许可/出处；
不主张仓库MIT能覆盖第三方程序或其派生程序。
源审阅镜像cenit/FEMM commit7d9e8ed90772ddb939a3256f976e231bcb5cca97，
仅作许可/API审阅来源，不把镜像commit说成2019安装包构建证明。
首个Archives URL取回非可执行文件的失败及Lua表达式协议错误保留Actions，
实际分发端点与Inno安装参数另有独立既有包来源，见契约。

可编程API为pyfemm/ActiveX：圆弧/区域/材料/线圈、实际转角磁化方向、
电路磁链、加权应力转矩、气隙B采样及本地fem/ans。
已有FEMM边界/永磁实现先通过独立有限边界圆柱解析解；
PMSM是原创合成无槽两极、线性背铁/PM模型，绝不冒充公开或用户实测电机。

后续替换：PYLEECAN几何/绕组、Elmer/GetDP独立场验证或另一PMSM可按同一SI
规范输出psi/L/转矩；本次没有采用PYLEECAN或给出跨求解器对照。
FOC仍执行固定motulator，不将静磁扫描当作逐时刻场-电路联合仿真。
