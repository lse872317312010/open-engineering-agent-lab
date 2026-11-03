# 公开有槽电机：PYLEECAN / SWAT-EM / FEMM

日期：2026-11-03。范围：部分P7-B；simulation-only，真机由用户负责。

[先行固定契约](p7-pyleecan-contract.md) /
[开源采用评审](../research/reviews/pyleecan-slotted.md) /
[实际原生求解](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41596131408) /
[原生模型与解](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41596131408/artifacts/13212208930) /
[五图离线报告](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41597944903/artifacts/13212872914)。

## 对象和实际执行链

直接采用固定PYLEECAN公开SPMSM_001 JSON，12槽/8极/三相双层，
每线圈34匝、每相136串联匝、50mm铁芯叠长、1mm气隙。
输入原文件SHA256：
`beba1fd4ed50e8c1d13743209a7e345ecd21a0ee9e64960c22a08924511cea06`。
不重新画一个相似模型冒充库执行：实际调用库的几何、SWAT连接矩阵、MagFEMM和结果积分。

| 依赖 | 固定源码 / 版本 | 许可 |
|---|---|---|
| PYLEECAN | 8654bd49fc005fdb19a38b1e39cd5d06198cdac1 | Apache-2.0 |
| SciDataTool | c6f2497971a24486c64ad27575eb45f12a8458bf | Apache-2.0 |
| SWAT-EM | 4d3b4d7093ba127b5bfbf4c6f2a038d87ba79d7e | MIT |
| FEMM / pyfemm | 4.2 21Apr2019 / 0.1.3 | AFPL |

源码按提交稀疏检出后直接导入，避免上游setup触发未固定的外部安装。
BH采用公开模型自带44点M400-50A表，不能声称独立核验了测量出处。
原JSON磁体Lmag=.95与铁芯L1=.05m不一致：原文件保持不改，
只检查2D截面与明确铁芯叠长，不据此解释磁体质量、端部或轴向损耗。

## 固定工况与单位

Kgeo/Kmesh=1/1.5/2，各含零流及正负[0,√3×2.5,−√3×2.5]A，
另细网格相对45°/90°零流与100mm双叠长，共12独立静态解。
所有求解频率为0；OP的60rpm用于库内部输入归一化，不能据此声称运行了转动或反电势。

PYLEECAN以原生FEMM深度1m建模，再沿实际叠长积分。
本适配读取原生problem-info深度，按Lmodel/Lnative换算磁链、加权应力转矩和滑移带MST，
分别与库物理输出对照。若把原生1m数据直接当50mm，会造成20倍错误。

相对角0°对应实际绝对22.5°，额外45°/90°对应67.5°/112.5°。
每一解保存实际/期望绝对角与误差，≤1e−12rad。
本轮尚未校准控制器dq零位，电流只称明确abc激励，不称iq。

## 实际结果

| 项目 | 实际值 | 先行门槛 |
|---|---:|---:|
| 三档节点 / 三角形 | 22317/40734、50292/91888、91283/167080 | 逐档增密 |
| 中→细磁链向量差 / 0.05Wb | 0.0013256693（0.1325669%） | ≤0.03 |
| 中→细转矩最大差 | 0.0041889676N·m | ≤0.05N·m |
| 45°磁链反向差 / 0.05Wb | 4.5571e−6 | ≤0.02 |
| 90°磁链重复差 / 0.05Wb | 1.5074e−8 | ≤0.02 |
| 双叠长磁链/转矩与原生气隙场差 | 0 / 0 / 0 | 各≤1e−6 |
| 库物理输出与手动叠长换算 | 12点磁链/转矩差均0 | ≤1e−8 |
| 原生区域面积最大相对差 | 0.0499845% | ≤0.5% |
| 实际转角与期望值差 | 12点均0rad | ≤1e−12rad |

细网格零流λabc=[0.0649692069662,−0.0332468823212,−0.0332454662300]Wb。
正负明确abc电流的加权转矩约+1.998303606/−1.996172966N·m。
静态幅值与单位均逐点保留，未从这些点拟合Ld/Lq。
原生证据24份fem/ans，31.96MB；Ruff通过，原生环境pytest **228通过、25跳过**。

槽/磁体独立扇形面积和铁芯环形减槽面积不依赖FEMM装配；
SWAT实际矩阵[1,2,12,3]，24非零线圈边，逐相有符号匝数和为0。
轮廓多边形与独立槽面积相对差约1.7483e−6。
固定门槛见契约，不通过事后扩大误差预算处理失败。

加权应力与滑移带MST、库输出共享同一FE解，
接口一致不能替代独立PMSM场求解器精度。
零流小残余转矩跨网格变号，本轮固定绝对预算不证明齿槽转矩精度。

## 证据与交互

数值生产提交 `1d53e7f2982bf3dcfbe5aeb50bdcb22baacd9a64`；
报告生产提交和原生生产提交分别显示。
重建报告先逐文件验证85份manifest条目及每个原生fem/ans哈希、
原JSON哈希、12点全门槛与数值生产者源码一致。
只接受完整通过的原生阶段，报告与浏览器必须重新运行。

报告显示实际几何轮廓、24线圈边的相别/匝数/电流/安匝、8磁体、
48条取自96点原生气隙场的矢量；12工况与三网格筛选可切换。
原生1m与实际叠长、三相磁链、两路转矩、区域面积和每项状态分别展示。
提供15份完整CSV、3JSON、五页PDF及PNG/SVG，另附许可/契约/源码身份。
解压报告后打开p7-pyleecan-report/index.html；报告不需联网。

实际Chrome156.0.8078.48验12状态、19份下载逐字节SHA与CSV行数、
组件点击/Enter/Space、网格筛选与Home/End、五图加载、390px无横向溢出。
页面错误/外部请求为空；报告包2.56MB。
报告提交`7b2b98aea8ca48deccd89f4e4950d7bb11c7bd18`，
[报告运行41597944903](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41597944903)通过；
同头8项CI/三Python版本/P1/P5/ARM/P6/报告检查均成功。

## 已发现的失败与修复

- 初次几何序列化遇NumPy布尔类型；修复编码，几何公式和门槛保持。
- 官方安装包一次下载超时；增加有上限的重试，仍检查PE结构和既定SHA256。
- [旧完整运行41593916408](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41593916408/artifacts/13212520097)
  的12点局部门槛/网格/叠长均通过，但转角对称失败。
  根因是上游InputVoltage把angle_rotor_initial=0当几何对齐哨兵，
  实际转角22.5°，原45°/90°却使用绝对角，比较零点不一致。
  在先行契约修订中明确origin=π/8后，统一给出origin+relative-angle，
  并增加实际输出角核验，保持原误差门槛，重新求解全部12点。
- 首个诊断入口在激活固定源码前导入pyleecan，导致ModuleNotFoundError；
  调整入口顺序，[修正后的单点运行41596131395](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41596131395)通过。

- 首次完整浏览器报告在PDF下载超时：本地文件链接被Chrome内置PDF预览接管。
  改用精确字节的Blob下载并保留原CSV/JSON行为，重新验证所有导出和布局；
  原失败[运行41597622072](https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/41597622072)保留。

## 复现和剩余路线

`p7-pyleecan.yml`安装固定依赖/官方FEMM，依次运行：

```text
ruff check .
python -m pytest
python benchmarks/p7_pyleecan.py geometry
python benchmarks/p7_pyleecan.py
python benchmarks/p7_pyleecan.py archive
```

`p7-pyleecan-report.yml`下载固定运行的原生包，验证身份后运行：

```text
python benchmarks/p7_pyleecan_report_reuse.py
python benchmarks/build_p7_pyleecan_report.py
```

这是公开参考对象的有槽非线性静磁链路，不代表完整Gate B或整体P7完成。
下一步：同机型绕组/控制坐标标定、完整角步与网格收敛、
反电势和能量一致的非线性动态接口、独立公开PMSM基准/求解器对照，
再建立有出处的损耗到同一工程电机热FE/ROM空间映射。
现有合成等效板ROM和此前合成无槽电机FOC仍分别保持原验收范围。
