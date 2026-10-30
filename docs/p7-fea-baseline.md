# P7-A：首个已独立验证的开放有限元基准

2026-10-30，PR #37。本制造解基准状态为independently_verified；
是P7-A的部分增量，P7其余候选与电磁/整机/ROM工作仍待推进。
[固定契约](p7-fea-baseline-contract.md) /
[组件许可决策](../research/reviews/p7-fea-baseline.md) /
[实际运行40980679597](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40980679597)。

## 实际实现与范围

Gmsh4.13.1 CLI生成真实带标签三角网格，经meshio5.3.5进入scikit-fem11.0.0。
scikit-fem装配P1导热弱形式，SciPy1.15.3稀疏求解；
不是把RC网络重新命名为有限元，也没有自研通用FE求解器。
主包依赖、IR及原后端默认语义保持兼容。

0.1m×0.1m、厚0.01m方板，k=2 W/(m K)，四边25°C。
独立正弦制造解T=25+10 sin(pi x/L) sin(pi y/L)规定源、梯度与精确热量1.6W。
无时间状态、无对流或实物参数拟合。
证据model_simulated、source_kind analytic，只证明本方程与离散链路的数学正确性。

## 固定门槛的实际结果

实际执行提交`d63fe27f0e4e936410ea82261ae0589a07e9b1fa`，冻结契约/解析参考先于求解实现提交。
三档网格均核对标签1..4/10、坐标单位、四边各0.1m、
面积0.01m²、拓扑边界与标签节点一致。
最小单元质量0.8660，每档两次同输入MSH字节SHA256一致。

| 每边分段 | 节点 / 三角形 | 温升L2相对误差 | 梯度H1半范相对误差 | 直接边界热通量相对误差 |
|---:|---:|---:|---:|---:|
| 8 | 81 / 128 | 4.2266% | 19.4378% | 5.0327% |
| 16 | 289 / 512 | 1.0755% | 9.7926% | 1.2783% |
| 32 | 1089 / 2048 | 0.2701% | 4.9056% | 0.3209% |

L2阶数1.97449 / 1.99349，H1阶数0.98910 / 0.99725，均达到实现前门槛。
这些是全单元高斯积分误差，不是只对比节点。
最细源热量1.6000000000000034W，Dirichlet反力散热1.5999999999999968W，
直接梯度边界通量1.5948663883407983W。
最细自由方程归一化残差1.1346e-13、反力能量相对余额4.1633e-15。
反力余额是离散代数一致性，不能代替直接梯度通量的独立误差，也不代表物理测量精度。

三档端到端壁钟约0.255/0.251/0.277s，包含每档两次网格生成与文件输出；
稀疏求解约0.000632/0.000782/0.002288s。
它们是本宿主单次小问题记录，不是性能统计、硬实时或商业软件比较。
环境归档包含CPU信息、平台与累计峰值RSS：
本Python进程83044KiB、子进程99476KiB；
不是逐个网格的独立内存峰值。

## 真实测试与报告

lint通过；完整pytest **137通过、20跳过**。
本可选FE环境未安装motulator/FMPy等部分后端，跳过项不计为通过；
不同环境的通过数不能直接与前轮147通过/8跳过比较。
CI40980679542、P1/P5/P6及ARM相关回归已有成功记录；
部分长辅助工作流在归档时仍运行，不将其算作成功。

首次运行40913988075因错误固定不存在的Playwright1.51.1而在安装阶段失败，
没有产生有限元结果；本轮改用仓库已验证的1.55.0并完整重跑。
原数学方程、网格和误差门槛未放宽。旧361字节证据包不是场解交付。

[下载四图交互报告，2.84MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40980679597/artifacts/12944601783) /
[原始证据，0.34MB](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/40980679597/artifacts/12944547040)。
使用GitHub稳定artifact页面，不使用临时签名链接。解压打开index.html。
三档真实场与节点状态、热源→导热→恒温边界机制、四图PDF/PNG/SVG、
全部MSH/VTU/节点CSV与自由残差、网格日志和指标可检查。
单元填色采用三顶点平均温度，白圈为当前节点；精确值看节点卡片及CSV。

Chrome156.0.8078.47实际核对三档网格与真实三角形数、
节点端点及温度/解析值/误差数值、热源/反力/直接通量数值、全部CSV下载、
390px布局和图像/PDF。页面错误与外部请求为空。
实际CLI版本也核验为4.13.1，不仅检查pip包名。
环境、安装下载来源和所有输出SHA256在原始证据包归档；未分发Gmsh可执行文件。

## 复现

Ubuntu需libglu1-mesa运行库。完整步骤见
[工作流](../.github/workflows/p7-fea-baseline.yml)。

```bash
python -m pip install -r benchmarks/p7-fea-requirements.txt
python -m pip install -e ".[dev]"
ruff check .
python -m pytest
python benchmarks/p7_fea_baseline.py
python benchmarks/build_p7_fea_report.py
```

输出在outputs/p7-fea-baseline/与outputs/p7-fea-report/。
每次从实际结果执行固定Gate，不因包存在就标为通过。

## 后续边界

本轮尚无复杂CAD/STEP、Elmer/GetDP或FEMM/PYLEECAN接口，
也未证明PMSM电磁参数→FOC、真实分区材料/接触热阻、瞬态热、
ROM/400Hz、ANSYS对照或物理结温精度。
下一步按P7-A补充候选/工程对象与材料边界验证，再推进电磁场或分区热场，
不能从本纯物理基准跨级宣称P7-B/C/D完成。
