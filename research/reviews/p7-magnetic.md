# Gmsh/scikit-fem磁静态增量采用记录

决策：adapt。复用已采用Gmsh4.13.1 CLI、meshio5.3.5、scikit-fem11.0.0，
在独立benchmarks装配二维线性磁矢势Az弱形式，SciPy1.15.3求解。
这不是把热结果改名，而是独立电流源、磁阻算子、curl B、磁能/绕组磁链积分与解析验收。

既有许可证归档保持：Gmsh GPL-2.0-or-later及原specific exception（不据此推断所有集成豁免），
meshio MIT、scikit-fem BSD-3-Clause；仅可选实验环境安装，
第三方源码不复制到主包。报告随附完整原许可，磁静态方程/参考/几何和实现为原创。
既有P7-FE采用记录仍适用；未引入额外电磁求解器、受限电机几何或商业数据。

接口：physical-tag网格→Az/单元B/H→有单位单匝去回流L JSON/CSV/VTU/NPZ。
可替换性：后续FEMM/Elmer/GetDP独立求解器对照可读取同SI/边界/电流规范；
当前仅一个FE实现与独立解析真值，不宣称第三方求解器交叉验证。

有效域：线性各向同性、有限矩形边界、均匀DC去回流，无永磁、旋转/滑移、饱和、
涡流、磁滞、铁耗或真实槽绕组。L不是PMSM Ld/Lq，不写入现有电驱。
PYLEECAN/FEMM/Elmer候选不因本轮而被标记采用或完成。
