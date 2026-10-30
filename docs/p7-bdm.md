# P7-A：BDM1守恒通量与全域精度

2026-10-30。固定三工况×三网格及零源patch已独立验证，部分P7-A；
model_simulated/source_kind analytic。
[实现前固定契约](p7-bdm-contract.md) /
[上游空间及边界语义核验](../research/reviews/p7-bdm-flux.md) /
[实际工作流40989152180](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40989152180)。
实际执行提交`db2685db3d20dae871079a30b75ccd63d43e943b`。

## 结果：保留守恒，并改善本算例的全域通量

同一原P1温度和实际网格，保留P1/RT0/BDM1全部三方数据。
九组合的BDM1全域通量L2误差均小于原P1和RT0各自的一半，
达到实现前固定条件；三工况三档收敛阶1.9790–1.9938。

| 最细n32工况 | P1梯度全域L2 | RT0全域L2 | BDM1全域L2 | BDM1界面逐点局部RMS |
|---|---:|---:|---:|---:|
| layered | 1.70416% | 2.41554% | 0.019874% | 0.041211% |
| uniform-k | 0.75027% | 1.06380% | 0.001728% | 0.000726% |
| hot-ambient | 0.64522% | 0.91456% | 0.007524% | 0.002935% |

异质材料全域误差由P1的1.70416%、RT0的2.41554%，降为BDM1的0.019874%。
界面逐点RMS约0.041211%，原RT0约0.041237%，维持了界面精度。
界面RMS按局部解析通量幅值归一化，与全域L2不是同一尺度，不能相互比较。
与前轮“两侧功率差占局部解析幅值22.90%”也不是同一指标。

BDM1包含完整仿射向量，可表示本问题各区的方向性线性通量，
而RT0的a+b*x（b为单标量）不能完整表示。
这说明本制造解中改善的原因，但不保证复杂几何、变系数或非线性问题也有相同误差/阶数。
零源n8补丁全域L2约1.33e-14，属于数值极限，不是物理测量精度。

## 边界数据：同一温度，表示能力不同

求最小1/2∫|q+k grad(T_P1)|²/k，逐单元约束∫div(q)=∫s。
使用scikit-fem11.0.0 ElementTriBDM1与SciPy1.15.3；
复用Gmsh4.13.1/meshio5.3.5，无新增依赖，不复制上游元素或求解器实现。
原温度NPZ与数组前后校验不变，Gmsh MSH字节hash和节点坐标对齐。

上下法向为0，右侧物理公式仍为h*(T_P1-Ta)：
- RT0每facet一个法向DOF，只保留面平均；
- BDM1每facet两个法向DOF，可保留原P1边温的线性分布。

BDM右边界用实际法向基函数边L2质量矩阵投影，
不把BDM系数直接当成密度或边积分。
因此这是同一温度来源下、空间和边界表示能力的共同比较，
不能描述成只增加内部自由度。
投影函数不导入解析参考，不接收真实热流；解析解只参与独立评价。
这仍是原温度的后处理，不是新的独立温度后端。

## 守恒与局部审计

九组合最大几何单元余额/功率尺度约5.92e-16，
内部法向完整迹差最大约2.86e-13W/m²。
实际边积分与两个DOF的法向矩乘积差最大约2.0e-15W/m；
右边完整迹对原P1 Robin公式以及上下零通量的最大差约1.14e-13W/m²。
几何法向、原边界总功率保持、翻转内部DOF故障拒绝均通过，
热环境右向外功率约-0.03380952W，保留反向入热。

这些首先证明离散约束满足，不单独证明准确；
均值积分准确还受区域源和原边界积分约束，
所以继续独立检查全域通量及界面facet内每个高斯点。
每facet四个高斯点，界面CSV为32/64/128个积分点评价；
不像RT0那样只存每facet一个常值法向密度。

BDM通量DOF为816/3168/12480，RT0为408/1584/6240。
此处DOF数翻倍，不表示计算耗时恰好翻倍。
n32各场景单次端到端约0.49–0.61s，包含重建网格、求解、审计和文件输出；
不是纯求解器计时、重复统计、400Hz或目标硬实时验收。
CPU/平台、进程峰值RSS和全部环境/壁钟元数据在原始包。

## 报告与验证

[四图交互报告，9.44MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40989152180/artifacts/12947609522) /
[原始证据，12.06MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40989152180/artifacts/12948531115)。
解压打开index.html。三场景/三网格，三方界面/全域误差、
实际BDM单元平均通量/原P1温度/源项/散度/余额、
边界有符号功率和原温度未修改状态分别展示。
对比提示按实际数据计算改善组合数，不预设所有问题都会改善。

四图PDF/PNG/SVG、VTU、完整cell/facet CSV、界面逐高斯点CSV、
每facet法向迹最小/最大值、原网格/场、BDM系数、
双facet-DOF映射及法向矩权重/完整迹NPZ可导出。
基函数坐标系数不是通量密度，物理密度/积分/功率另列并标明单位。

lint及完整pytest：**144通过、20跳过**。
新增实际BDM基函数的仿射张成性、RT0不能表示的独立反例、
边法向线性迹/积分极限测试，均通过。
原均匀制造解、分区P1和RT0全部固定验收在同工作流先完整回归。
同执行头CI/P1/P5/P6/ARM成功；可选后端跳过不计通过，既有范围没有扩大。
Chrome156.0.8078.47实际验九组合图元、功率/单元数值、误差对比提示、
全部CSV下载/实际行数、键盘端点、390px和PDF；无页面错误或外部请求。
全部新数值/浏览器验收首轮通过，门槛未按输出调整。

## 复现与范围

```bash
python -m pip install -r benchmarks/p7-fea-requirements.txt
python -m pip install -e ".[dev]"
ruff check .
python -m pytest
python benchmarks/p7_fea_baseline.py
python benchmarks/p7_layered.py
python benchmarks/validate_p7_conservative_flux.py
python benchmarks/validate_p7_bdm_flux.py
python benchmarks/build_p7_bdm_report.py
```

Ubuntu需libglu1-mesa，完整步骤见[工作流](../.github/workflows/p7-bdm.yml)。
主IR、电驱及原P1/RT0默认语义未改变。
尚无接触热阻、瞬态、真实器件几何、电磁损耗映射、ROM或实测温度精度。
下一步按P7路线图继续工程边界与时域/降阶验证，整体P7仍未完成。
