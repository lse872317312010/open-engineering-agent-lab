# 磁静态Az、磁链与有限域单匝电感

四工况×三网格的真实Gmsh/scikit-fem磁静态求解及离线报告通过冻结门槛。
[物理契约](p7-magnetic-contract.md)与独立解析测试先行；
[开源采用评审](../research/reviews/p7-magnetic.md)限定线性有限矩形磁路。
实际执行源码adcc76f6e92200f390d4363e2b053f3ba834d69d，[完整专项](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41398648374)成功。

## 物理、单位与接口

域为.1m×.1m，x=.04m分区，轴向深度.01m。
去流在左区、回流在右区均匀分布，区域积分±I；
工况为空气2A、右区5μ0的2A、反向−2A和倍流4A。
I是DC支路电流，单匝，没有RMS、dq或极对数换算。

求解−div((1/μ)grad Az)=Jz；
Az单位Wb/m，B=(∂yAz,−∂xAz)T，H=B/μ A/m。
左/右边Az=0，上/下自然Neumann；界面共享Az，H切向连续由弱形式近似。
材料合成且线性、无磁滞/永磁/饱和；有限域边界不代表无限自由空间。

K与电流f按真实标签装配，不输入解析解；
独立二次分区Az由Ampere定律给出，用于全场L2评价。
几何单元积分W=depth/2∫B²/μ dS；
单位电流绕组g=Jz/I，lambda=depth∫g Az dS；
L=lambda/I=2W/I²。
独立解析L=depth*(μleft*.04+μright*.06)/(12*height)。
能量/磁链共享离散场，故一致性检查不被算作第二个独立场求解器。

每组parameters.json导出format_version、quantity、L/H、lambda/Wb、W/J、
电流约定、几何、材料、边界、source_kind与scope。
quantity为bounded_single_turn_return_pair_inductance；
没有将这几个nH参数伪装成PMSM Ld/Lq，现有FOC和IR不改。

## 三网格实际结果

每区间隔n=8/16/32，对应153/561/2145节点和256/1024/4096三角形。
两次实际Gmsh生成同输入字节hash一致，标签/面积/边界/拓扑检查完整。
最终采用交替对角线网格，物理、P1空间和节点数均保持。

| n32工况 | 有符号I A | 提取L nH | 独立L nH | L相对差 | Az相对L2 | B相对L2 |
|---|---:|---:|---:|---:|---:|---:|
| air | 2 | 1.0464391 | 1.0471976 | 0.072427% | 0.079501% | 2.69122% |
| contrast | 2 | 3.5578508 | 3.5604717 | 0.073611% | 0.079828% | 2.71996% |
| reverse | −2 | 3.5578508 | 3.5604717 | 0.073611% | 0.079828% | 2.71996% |
| double | 4 | 3.5578508 | 3.5604717 | 0.073611% | 0.079828% | 2.71996% |

Az阶2.009–2.020、L阶2.007–2.015、B阶1.004–1.007。
全场B误差明显大于L误差，不用一个积分参数的精度代表整个场。
最大自由残差相对值2.00e−13，源积分误差2.23e−16；
几何/矩阵磁能差5.82e−15，lambda I与2W差7.10e−15，
规范平移磁链差1.05e−15。它们证明离散账一致，不能替代上表解析误差。

反向磁链/场取负、能量和L不变；倍流磁链/场双倍、能量四倍、L不变，
全部受检相对差为0。最细网格实际解零电流，Az/B/能量为0。
故障副本翻转B的场相对差2、漏深度L差98.926、错误回流的规范变化7.951，
均超过先行固定拒绝线；正常方程没有被改成故障副本。

## 保留失败与网格方向性

[原默认方向网格完整失败证据](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41397483081/artifacts/13119269087)，
运行41397483081、源码051f0f22292723f3894ecd66949f41c68b555df4。
该网格全场/电感收敛、能量、线性/零源/故障检查均通过，
但高μ工况n8的直接P1界面H双侧最大差5.37555%超过冻结5%，整轮标为失败。

先提交网格复验说明f49cbdfb00c269977fab19af4ee4b9a932447634，
再用Gmsh Transfinite Surface Alternate减少固定对角线方向偏置。
不改变物理、源、边界、间隔、节点/单元数、积分、解析真值或任何门槛。
该粗网格双侧差降至0.23884%；n32降至0.05916%。
但n8两侧对解析H仍差10.42%，n32仍差2.6064%：
两侧接近不等于两侧都准确，报告第四图显示解析迹而非只画相互差。
旧默认网格三个hash逐字节复现，旧双材料默认热算法通过三工况/三网格回归。
原失败12组数据随最终validation.json保存，旧完整场仍在独立失败artifact。

## 报告、数据与验收

[四图交互报告5.58MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41398648374/artifacts/13120940769) /
[原始证据3.02MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41398648374/artifacts/13120671818)。
解压打开index.html，全部资源离线；链接使用稳定GitHub artifact入口，可能需要登录。
报告显示电流/μ→磁阻K→Az→B/H→磁能/磁链→电感机制，
可选四工况、三网格和Az/By/Hy，查节点与单元状态、材料及方向，
并列旧/新网格结果和明确保留的失败。
12个组合导出36完整节点/单元/界面CSV、12有单位参数JSON、VTU/NPZ、矩阵/绕组，
附磁场、收敛、反向/倍流、界面四图PDF/PNG/SVG。
JSON下载通过本地Blob提供原文件内容，避免Chrome离线打开JSON的下载兼容问题。

Chrome156.0.8078.47实际验全部12组合与真实多边形，
三种场量、节点/单元端点和内部数值、36CSV行数、12参数JSON与原内容一致、
键盘/390px/四图PDF，页面错误和外部请求为空。
Ruff通过，完整pytest204通过/23跳过；
该专项仅安装FE依赖，跳过的可选后端不计通过。
旧热制造解/双材料完整回归及同源码CI/P1/P5/P6/ARM均成功。

初次NumPy整数JSON序列化、报告网格键和离线JSON下载问题均已修复；
原数值失败、脚本失败与对应版本可在Actions追溯，未放宽物理门槛。
GEO/MSH/log、所有场/矩阵、零电流解、旧网格、安装provenance、
实际版本/OS/CPU/RSS与manifest SHA256在原始包中。
单次求解/导出约.010–.087s，不包含Gmsh/安装/报告，不声称硬实时性能。

## 复现与剩余工作

使用[专用工作流](../.github/workflows/p7-magnetic.yml)；
依赖固定为numpy1.26.4、SciPy1.15.3、Gmsh4.13.1、scikit-fem11.0.0、
meshio5.3.5、matplotlib3.10.1、playwright1.55.0，另需libGLU与Chrome。

```bash
python -m pip install -r benchmarks/p7-fea-requirements.txt
python -m pip install -e ".[dev]"
ruff check .
python -m pytest
python benchmarks/p7_fea_baseline.py
python benchmarks/p7_layered.py
python benchmarks/p7_magnetic.py
python benchmarks/build_p7_magnetic_report.py
```

证据model_simulated/source_kind synthetic，独立参照analytic；只将本磁静态基准
标为部分P7-A independently_verified，整体P7与Gate B未完成。
下一核心步骤是具体PMSM几何、槽绕组/永磁体、材料及转子位置，
真实FEMM/PYLEECAN或Elmer/GetDP候选复现，再做幅值/相序/磁链/转矩到FOC映射。
涡流/铁耗、真实电磁损耗空间映射和商业同条件对比仍待开展。
真机由用户负责，缺少硬件不阻塞仿真开发。
