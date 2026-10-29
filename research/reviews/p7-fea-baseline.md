# ADR：P7-A 首个场方程基准

2026-10-30。决策：Gmsh4.13.1 adopt（独立CLI），scikit-fem11.0.0 adapt
（可选制造解Poisson/导热基准），meshio5.3.5 adopt（网格与VTU交换）。
全部位于独立benchmarks环境，不进入oeal主包依赖，不改IR。
先用Linux可复现、范围很小的真实FEM验证建立边界/收敛/证据链。
scikit-fem是本轮新增候选，不替代路线图中Elmer/GetDP与FEMM的独立评测。

- Gmsh4.13.1：GPL-2.0-or-later及上游特定例外；原文归档。
  核验镜像tag commit 3862278e6705ecc0f5d32144289635a34f5d90cb，
  https://github.com/live-clones/gmsh/blob/gmsh_4_13_1/LICENSE.txt 。
  运行外部CLI，以原创.geo和MSH文件交换；不复制其实现，不在交付包分发可执行文件。
  此结构不构成对任意链接或再分发均无GPL义务的判断。
- scikit-fem11.0.0：BSD-3-Clause，非MIT；原文归档。
  commit f598e787feadcc63f077e41bf95d93a784f6c172，
  https://github.com/kinnala/scikit-fem/blob/11.0.0/LICENSE 。
  核验ex01的Basis/装配/Dirichlet API，原创热物理与独立参考；
  https://github.com/kinnala/scikit-fem/blob/11.0.0/docs/examples/ex01.py 。
- meshio5.3.5：MIT，https://github.com/nschloe/meshio/blob/v5.3.5/LICENSE.txt ，原文归档。
- SciPy1.15.3：复用既有许可审查；稀疏求解，不复制求解器。

Gmsh几何只用内置四边形与Transfinite控制，未采用FreeCAD/STEP或OCC实物几何。
参考算例是原创解析正弦热源，不使用许可不明的电机材料/几何数据。
依赖版本钉住，工作流保存实际安装环境、版本及wheel散列；
绘图/Playwright复用既有工具版本。只有实际CI证据通过后更新实施状态。
