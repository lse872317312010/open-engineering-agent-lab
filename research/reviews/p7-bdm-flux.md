# BDM1通量空间评测

2026-10-30，复用scikit-fem11.0.0 BSD-3-Clause（原文已归档）。
核验固定源：https://github.com/kinnala/scikit-fem/blob/11.0.0/skfem/element/element_tri/element_tri_bdm1.py 。
ElementTriBDM1：六个facet法向DOF，参考边两个Gauss点定义，
属于最低阶Brezzi–Douglas–Marini空间，包含完整仿射向量。
复用原ElementHdiv Piola/朝向、Basis/FacetBasis装配与SciPy稀疏求解。
没有复制上游基函数或求解器实现，后处理弱形式为本项目原创组合。

本轮新增BDM方法，不修改RT0以保持可重复对照。
BDM的DOF不是RT0的单facet积分，使用实际边质量矩阵投影边界，
并保存法向矩权重与两个facet DOF映射，避免伪造积分单位。
原P1温度、右边物理Robin公式和总功率保持；
RT0的常值facet边界与BDM的线性facet边界表示能力不同，结果必须说明。

预期解决上一轮BDM可表示而RT0不可完整表示的方向性线性通量。
只在原固定三工况/三网格先验收；不能从该制造解推广到工程复杂几何或ROM。
数学与门槛见docs/p7-bdm-contract.md。
