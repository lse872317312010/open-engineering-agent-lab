# PYLEECAN公开有槽参考模型采用评审

决策：adapt（可选benchmark环境）；不加入主IR/默认依赖。
固定版本：PYLEECAN 8654bd49fc005fdb19a38b1e39cd5d06198cdac1（源码模块1.5.2）、
SciDataTool c6f2497971a24486c64ad27575eb45f12a8458bf（模块2.5.0/setup元数据2.5.1）、
Eomys/swat-em 4d3b4d7093ba127b5bfbf4c6f2a038d87ba79d7e（0.6.3）。

PYLEECAN/SciDataTool在上述提交为Apache2，SWAT-EM fork在上述提交为MIT，
依实际LICENSE判断，不把其他同名发行版的许可自动套入。
PYLEECAN/SPMSM_001原JSON由仓库根Apache2许可提供，保留原文件与完整出处；
没有额外下载受限商业数据或把上游材料表当作已核验的实测真值。
副本见benchmarks/assets/pyleecan-spmsm001.json，原始SHA在实际运行时与固定源码核对。

PYLEECAN的setup.py会主动安装未固定的GitLab SWAT-EM，因此本采用路径不运行setup.py。
三个仓库按固定commit只读检出，通过隔离sys.path导入未改源码；
轮子依赖逐版本固定，QtPy选PySide6，实际pip安装报告/freeze/许可证留档。
报告不携带Qt/FEMM等程序二进制。FEMM/pyfemm AFPL采用边界沿用p7-femm-motor.md。

实际使用库load、几何、SWAT绕组生成和MagFEMM/原生滑移带。
独立扇形面积、矩阵匝数、原生区域面积、叠长归一化与指定转角对称性逐项核验。
不重画一个原创模型后冒称运行PYLEECAN。轴向Lmag=.95与铁芯.05m不一致，
未悄悄修改数据；本轮禁用依赖该字段的质量/磁体损耗与端部解释。
当前仅公开参考数据与model_simulated等级，不代表测量、完整工程对象或第三方场真值。
