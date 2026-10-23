# 2026-10-23 分支清理记录

用户授权清理多余分支。检查基线为 `0d08eb8ec8017fcaa0113b76a8362fc366e07b26`。

- 8 个功能分支的 PR 已合并，提交头均为 main 的祖先，删除分支名不丢失提交历史。
- PR #1 / #2 的代码、测试及专门说明文档与 main 的 Git blob 完全相同；
  它们只有早期路线图和未合并的提交身份需要保留。删除前以固定 archive 标签保存完整头提交，
  并关闭已被主线覆盖的旧 PR。
- 操作前再次核对所有远端头 SHA；使用 Git 原子推送和 force-with-lease，
  任一分支发生新提交就拒绝整批删除。不会扫描删除其他未来分支。
- 架构文档工作分支仅在合并为 main 祖先后删除；始终保留 main。
- 实际执行结果见 [维护工作流](../.github/workflows/architecture-maintenance.yml)
  的 `branch-cleanup-2026-10-23` 工件中 `cleanup-applied.json`；本文件是固定计划和恢复索引。

| 分支 | PR | 处理依据 | 完整头提交 / 归档 |
|---|---:|---|---|
| codex/arm-qemu-pil | #6 | 已合并 | `08fdf767e52717e2ae4c5450e24f111c58eb2635` |
| codex/dq-current-pi | #2 | 主线代码相同；保留归档 | `archive/2026-10-23/dq-current-pi` |
| codex/foc-transform-foundations | #1 | 主线代码相同；保留归档 | `archive/2026-10-23/foc-transform-foundations` |
| codex/open-model-refinement | #9 | 已合并 | `560adc23bfc746a435322113e8d852929d648517` |
| codex/p6-multiphysics-report | #7 | 已合并 | `c4020d70e1a1ed00086febd43abfdde6dfb083cb` |
| codex/report-system-model | #8 | 已合并 | `9d52767fc747c30831962f1ecf6024a10a96797f` |
| codex/roadmap-p1-p5 | #3 | 已合并 | `f8b57ff618dbfd161353db6130f741a443037c27` |
| codex/simulation-only-acceptance | #5 | 已合并 | `cb77db9ace3e1206129e1fde2930588be9e83f3f` |
| codex/stm32-f32-pi | #4 | 已合并 | `f3d6df19db3786ac177329f8916ac8298ff480b5` |
| codex/unified-studies-and-design | #10 | 已合并 | `b7f94e7bafc81496040a717ecdf582bc9948fac3` |

归档标签：
- `archive/2026-10-23/dq-current-pi` → `3749d84f9708dd821ad62cc85f8fdc64e9b46b5b`
- `archive/2026-10-23/foc-transform-foundations` → `22f4b6d564c72b28c2328e886bdb7925c0db609b`

如需恢复早期历史，可从相应归档标签创建新分支。已合并分支也可从上表头提交恢复，
没有重写 main 历史或修改应用代码。
