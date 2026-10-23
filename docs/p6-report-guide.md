# P6 报告交付与复现

本轮依照仿真验收约束推进；真机由用户负责。
数学模型、独立参考和固定阈值见 [模型契约](p6-model-contract.md)。

## 取得报告

在 PR #7 的 **P6 multi-physics evidence and report** 工作流中，
下载 **p6-report-and-evidence** artifact：
- report/index.html：离线中文交互界面，直接双击打开，无需服务器/账号/网络；
- p6-report.zip：独立报告包，解压后打开 index.html；
- report/report.pdf：五页标准图表与方法说明；
- report/plots/：4 组 PNG/SVG，可用于文档或演示；
- report/data/ 与 data.json：完整 CSV 与结构化报告；
- report/ui-*.png、ui-validation.json：实际桌面/暗色/移动端截图和浏览器交互验收；
- p6/：独立参考、标定、全部参数输入、FMU 和复现环境；
- manifest.json：整个交付物的文件散列。

GitHub artifact 有保留期限，下载后可按 manifest 校验并自行留档。
交互图每 4 个控制样本取 1，原始 CSV 保持完整采样。
界面控制仅浏览已计算工况，不会把预计算曲线伪装成实时求解。

## 人机交互

工况切换、基准叠加、键盘/拖动时间游标、当前参数说明、
热阻与高负荷场景切换、深浅主题、CSV/JSON 和 PDF/PNG 导出。
未达目标和命令停机具有独立状态；图表轴标单位，指标注明来源。
响应式界面在 1440px 桌面与 390px 手机视口检查，
使用 CI 现有 Chrome 与 Playwright，验证离线运行和导出，不依赖浏览器下载站。

## 可复现命令

Python 3.12 + GCC；图表需要 Matplotlib，FMU 运行需要固定 FMPy，
UI 测试需要已安装的 Google Chrome；生成中文 PDF 可安装 fonts-noto-cjk。

```bash
pip install -r benchmarks/p6-requirements.txt
pip install -e ".[dev]"
ruff check .
python -m pytest
python benchmarks/validate_p6.py
python benchmarks/validate_fmi_thermal.py
oeal simulate-joint examples/p6-joint.json --output outputs/p6/cli
python benchmarks/build_p6_report.py
python benchmarks/validate_report_ui.py
python benchmarks/evidence_manifest.py
```

## 范围

实现：9 状态电气/双惯量/三节点热耦合、平均逆变器纹波/死区代理、
采样更新与一周期延迟接口、命令停机事件、合成标定与独立验证、
±20% 相关热阻场景扫描、单节点 RC 的 FMI 2.0 互操作。
短时全耦合与 120 s 理想电流热包络分别报告。
未实现完整关节 FMU/OpenModelica、开关级器件/ADC 孔径/ISR 抖动、
齿隙接触或真实数据标定；不将合成误差当作实测偏差。
