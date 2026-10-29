# P7-A 首个开放有限元基准

状态：实现已提交PR #37，专项执行尚在GitHub runner队列，**未验证、未合并**。
[运行入口](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40911466364)。
[实现前固定契约](p7-fea-baseline-contract.md) /
[组件与许可决策](../research/reviews/p7-fea-baseline.md)。

## 实现范围

Gmsh4.13.1独立CLI生成0.1m方板的三档真实网格；scikit-fem11.0.0
装配P1稳态导热弱形式，SciPy稀疏求解。meshio5.3.5负责MSH/VTU交换。
每边8/16/32段，分别128/512/2048个三角形。
温度、源项、梯度和总热量由独立正弦制造解规定，精确总热源1.6W。
原有电驱、RC、IR和默认依赖保持兼容。

输入方程、单位、误差门槛、网格质量和边界标签要求已经冻结。
需要实际工作流产生证据后，才能将该基准标记为independently_verified；
目前不填写推测的误差、耗时、通过数或产物链接。

## 复现命令

Linux需要Gmsh共享库的GLU运行依赖，例如Ubuntu的libglu1-mesa。
固定可选环境与完整步骤见
[专项工作流](../.github/workflows/p7-fea-baseline.yml)。

```bash
python -m pip install -r benchmarks/p7-fea-requirements.txt
python -m pip install -e ".[dev]"
ruff check .
python -m pytest
python benchmarks/p7_fea_baseline.py
python benchmarks/build_p7_fea_report.py
```

预期输出位置outputs/p7-fea-baseline/与outputs/p7-fea-report/。
只有实际通过时，validation.json和ui-validation.json才会记录passed。
若失败，保留真实日志和结果，不根据结果放宽契约门槛。

## 验收与报告设计

- 四条恒温边界的几何身份、physical标签、长度与拓扑边界一致性。
- 网格面积、三角形质量、节点/单元数；两次同输入MSH字节hash重现。
- 三档全单元积分L2/H1误差与收敛阶；自由方程残差。
- 体积源积分、Dirichlet反力和直接梯度重建的边界热通量分别核对。
- 四图PDF/PNG/SVG、真实MSH/VTU、全节点CSV、环境/安装来源与SHA256。
- 中文离线页面显示热源→导热→恒温边界机制，切换三档网格及节点状态。
  单元填色以三个顶点的平均温度显示，白圈表示当前节点；
  精确场值和误差由节点卡片与CSV提供。浏览器检查须实际运行才算通过。

这是P7-A的有限增量，不代表已完成所有候选评测。
复杂CAD/STEP、Elmer/GetDP、FEMM/PYLEECAN、电机电磁、瞬态热、
ROM/400Hz、ANSYS对照与实测精度继续列为待办。
