# RT0守恒通量后处理选型

2026-10-30。复用scikit-fem11.0.0 BSD-3-Clause（原文已归档），无新增依赖。
有限采用其H(div)元素、Piola映射、facet朝向与弱形式装配，
SciPy解约束鞍点系统；不复制其元素/求解器实现。

已核验固定11.0.0源码：
- https://github.com/kinnala/scikit-fem/blob/11.0.0/skfem/element/element_tri/element_tri_rt1.py
  类说明为lowest order；每facet一个DOF，局部边法向积分为1。
- https://github.com/kinnala/scikit-fem/blob/11.0.0/skfem/element/__init__.py
  ElementTriRT0 = ElementTriRT1，别名不是高阶RT1。
- https://github.com/kinnala/scikit-fem/blob/11.0.0/skfem/element/element_hdiv.py
  用f2t[0]定义facet朝向，Piola变换使用映射行列式和朝向符号。
- https://github.com/kinnala/scikit-fem/blob/11.0.0/docs/examples/ex37.py
  真实混合Poisson/RT元素API；本轮为原创约束后处理，未复制该算例。

数学与预先门槛见p7-conservative-contract.md。
不能把RT0法向连续、局部守恒或积分准确，单独解释为逐点通量准确。
保留原梯度法作为对照；使用解析解只评价，不参与投影。
