# 非线性散热配置与秒级联合复现

本轮接口位于benchmarks/msl_cooling_drive_adapter.py的可信Python对象MSLCoolingDrive。
依赖固定MSL生成的outputs/msl-cooling/OEALMSLCooling.fmu，不由实验JSON选择任意FMU资产。
核心七IR配置和默认原生后端不变。

| 配置项 | 单位 | 默认 | 接受范围 |
| --- | --- | --- | --- |
| ambient_c | °C | 25 | −10..60，有限实数 |
| initial_temperatures_c | °C | 六个80 | 六有限实数，各−10..120 |
| area（Gr） | m² | 调用方明确提供 | 0..0.1，有限实数 |
| varying | 布尔 | False | 固定Gc或预声明连续Gc函数 |

六节点顺序：绕组、铁芯、壳体、结温、板、散热器。
初态在FMI初始化完成后投影，初始输入热及三条散热积分均为零；
这指定一个合成状态，不意味着模型模拟了此前升温或注入了初始热量。
全部储能变化以实际初态为基准，环境热流以配置环境为基准。
负环境热流表示由暖环境向节点输入热量；不得裁为零。
Gc为等效W/K、Gr为有效m²，均无风机转速、CFD或实物标定含义。

```python
from pathlib import Path
from msl_cooling_drive_adapter import MSLCoolingDrive

provider = MSLCoolingDrive(
    Path("rhs.csv.gz"), duration=1., area=.02,
    ambient_c=25., initial_temperatures_c=[25.]*6,
)
# 将provider传给已固定的run_drive(..., thermal_provider=provider)。
# 求解完成后在finally中调用provider.close()释放实例与原始记录。
```

在仓库根目录将benchmarks加入Python模块路径，并先完成固定依赖及FMU构建。
推荐直接执行工作流所列脚本，避免漏掉兼容性对照所需的基线检出。
[完整工作流](../.github/workflows/msl-configured-drive.yml) /
[固定Gate](msl-configured-drive-contract.md) /
[实际结果](stage-status.md)。

实验输出分别为outputs/msl-cooling-drive（原短时热初态回归）、
outputs/msl-configured-drive（新环境/初态及秒级实验）及对应-report目录。
每组保留input.json、实际/参考控制和能量、电磁细流、完整RHS及故障副本；
报告保留全部CSV，页面回放抽样而科学Gate读取全量。
1秒联合验证仍不同于一小时热回放、电机耐久或机器人整机验证。真机由用户负责。

报告测试单独修复时，工作流的[report-only]模式只复用已归档科学run40613204776。
恢复任务核对科学源码/契约、全部保留数据manifest及Git差异允许清单；
科学/依赖改变即拒绝复用。正常推送或workflow_dispatch仍运行完整编译、14组仿真与双报告。
该缓存依赖原始artifact保留期，不能下载或哈希不符时须走完整科学运行。
