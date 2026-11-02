# pyMOR2026.1.1：固定接触板POD的有限采用

2026-11-02。决策：adapt，仅可选benchmarks中的质量POD/正交化；不注册通用后端。

上游https://github.com/pymor/pymor ，tag 2026.1.1；
annotated tag对象b79825d259ab301d7be93b1ad22947cc15a452c6，
目标commit36a0035e180694c7ad4eb8f083d9f1d65ceb6f42（读取GitHub tag资源核对）。
pip版本精确钉住pymor==2026.1.1；运行实际导入版本匹配，wheel来源/hash保存在pip-install.json。
上游tag源码核验与pip安装来源分别记录，不宣称自行可复现构建过wheel。

核验API：algorithms.pod.pod接受product=NumpyMatrixOperator(M)，最多12模态；
algorithms.gram_schmidt.gram_schmidt用于先放区域指示向量的增强基底。
此版本NumpyVectorSpace.from_numpy/to_numpy以(dim,count)列向量布局使用；
实际测试非方阵3×4往返、质量正交与满秩投影，避免沿用旧版行布局假设。
不复制上游POD/SVD/Gram-Schmidt实现，调用实际安装库。

许可证：POD/Gram-Schmidt BSD-2-Clause；
项目pyproject.toml整体声明BSD-2-Clause AND BSD-3-Clause，包含来自SciPy的通用求解器代码。
归档[主许可](../licenses/pymor-2026.1.1-LICENSE.txt)和
[打包软件声明](../licenses/pymor-2026.1.1-LICENSES_bundled.txt)，报告也含两者。
保留版权/许可/免责声明和第三方条款；不把整个包简化为仅BSD2，
不据此替用户提供所有分发场景的法律结论。

环境：Python3.12、NumPy1.26.4/SciPy1.15.3、单BLAS/OMP线程、原Gmsh/scikit-fem分离环境。
实际采用只需POD/正交化；未使用神经网络、MPI、Qt GUI、平衡截断、误差界或pyMOR全部reductor。
时间积分仍使用既有物理约定的SciPy CN。主IR/主依赖不变。

替换方式：基底和Mr/Kr/Fr/物理输出以NPZ导出；
评价过程只需NumPy/SciPy矩阵，不要求在线导入pyMOR。
当前脚本整体仍导入FE训练模块，并非已经打包好的独立嵌入式推理库；
C导出、目标同步和参数化ROM须后续单独验收。

[结果和限制](../../docs/p7-rom.md) /
[实现前契约](../../docs/p7-rom-contract.md)。
