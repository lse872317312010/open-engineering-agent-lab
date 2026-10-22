# 实验记录

每个可引用实验使用单独目录，建议包含：

```text
experiments/<日期>-<简短名称>/
  question.md       假设、依据、模型适用范围和验收标准
  input.json        完整仿真输入
  summary.json      求解器生成的指标摘要
  trace.csv         求解器生成的轨迹
  result.md         结论、偏差、失败情况和下一步
```

不要覆盖历史实验目录。大型、可再生的轨迹文件可以不纳入 Git，但 `input.json`、结论和代码版本必须保留。

