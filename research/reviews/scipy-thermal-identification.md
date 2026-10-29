# SciPy六节点热参数辨识有限采用

采用现有固定环境SciPy1.15.3的optimize.lsq_linear（有界线性最小二乘）、
linalg/NumPy SVD诊断及integrate.solve_ivp(Radau/DOP853)。
未新增求解器依赖或复制优化器代码；积分特征、数据分组及门槛为本项目原创连接实现。

[固定版本源](https://github.com/scipy/scipy/blob/v1.15.3/scipy/optimize/_lsq/lsq_linear.py)
确认lsq_linear的上下界、trf、tol、max_iter和result.active_mask/optimality/nit语义；
使用公开接口，保存实际最优性、界限状态及归一化设计秩/条件数。
[上游LICENSE](https://github.com/scipy/scipy/blob/v1.15.3/LICENSE.txt)为BSD3；
原文保存在research/licenses/SciPy-1.15.3.txt并随报告分发。

结论adopt（仿真范围）：完整六节点温度与已知热源下，窗口积分把C和G=1/R写为线性未知量，
避免直接微分测量噪声；归一化后检查激励充分性，再有界求解。
估计参数随后加载真实MSL FMU，与未参与拟合的两组数据比较；
独立Radau对照用于区分参数误差和数值交换误差。
这不覆盖稀疏传感器、未知热源、真实器件参数或MSL与现实结构不一致的辨识问题。
