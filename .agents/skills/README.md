# 项目 OpenSpec 工作流 Skill

本目录是**项目内** OpenSpec 工作流 Skill 的语义维护来源。仓库里有两份平行副本：

| 目录 | 面向 | 地位 |
| --- | --- | --- |
| `.agents/skills/` | Codex | **语义维护来源**：规则改动先落在这里 |
| `.claude/skills/` | Claude Code | 同步副本：业务规则必须与上面一致 |

两份都是 OpenSpec CLI 生成后经过本项目定制的版本，包含同样的六个工作流：

```text
openspec-propose        生成新 change 的规划产物
openspec-update-change  修订已有 change 的规划产物
openspec-apply-change   实施 / 继续实施 change 的任务
openspec-explore        实施前的方案探索
openspec-sync-specs     把 delta specs 合并进主规格
openspec-archive-change 归档已完成的 change
```

## 一、允许存在的差异

两份副本**只允许**在客户端命令写法上不同：

```text
.agents/  →  `$openspec-apply-change (Codex) or /openspec-apply-change (other agents)`
.claude/  →  `/openspec-apply-change`
```

除此之外的一切——`description`、步骤、判定分支、guardrail、路径与校验要求——必须逐条一致。

**不要用文件哈希或 `diff` 有输出来判定两边规则冲突。** 上面的命令写法差异会让每个文件都有 diff。
核对方式是：把命令写法之外的行拿出来比对，或直接逐条核对下一节列出的规则点。

## 二、必须一致的规则点

修改任一副本后，逐条确认另一份也改到位：

1. `description` 的触发范围（决定 Skill 什么时候被自动选中）；
2. 何时停下来问用户、何时继续执行；
3. 规划与实施的边界（哪个工作流允许写应用代码）；
4. 产物路径来源（`existingOutputPaths`、`planningHome.root` 等），不得改成硬编码路径；
5. 规格同步的完整性检查、失败后不归档、目标已存在保护、能力删除保护；
6. 不删减需求、不虚假勾选完成。

## 三、当前定制内容（2026-09-16）

相对上游生成版本，本项目做了以下修改，依据见 `plans/2026-09-16-agents-and-skills-remediation.md` 任务 4：

| Skill | 定制 |
| --- | --- |
| `openspec-propose` | 收窄 `description` 到「明确要求 OpenSpec 提案」；删除「即使用户已要求实现也必须等下一条消息」，改为：只要提案时停止，已授权规划并实现时产物就绪后转 apply。Skill 本身仍只写规划文件 |
| `openspec-update-change` | 收窄 `description`；删除逐 artifact、逐 edit 确认，改为已授权的一致性修订成组完成，只有新增实质决策才集中确认；已授权实现时允许交接 apply |
| `openspec-apply-change` | 收窄 `description`，说明普通编码请求不因含 implement 就触发；普通编译/测试失败与必要辅助修改继续调查修复，只有无法安全处理的阻塞、重大歧义、范围或权限变化才停 |
| `openspec-explore` | 收窄 `description`；删除「先退出 explore 模式」的口令要求，用户明确要求实施时直接转合适工作流 |
| `openspec-sync-specs` | 收窄 `description`；普通措辞与可确定的格式问题自行处理，只有需求语义冲突才询问 |
| `openspec-archive-change` | 收窄 `description`；用户已在本次会话表达过的同步/归档决定直接复用，不重复询问 |

**未改动**（刻意保留）：store 选择、CLI 返回路径、`existingOutputPaths` 子集约束、源内容保护、
规则快照、校验失败不称成功、能力删除保护、未完成任务提示、同步失败不归档、目标已存在保护。

## 四、上游更新后的检查清单

OpenSpec CLI 重新生成或升级这些 Skill 后：

- [ ] 逐条核对上游新规则与第三节的定制是否冲突，**不要机械覆盖**，也不要假定旧的定制永远适用；
- [ ] 确认上游没有重新引入被删除的条款：逐 edit 确认、「即使用户已要求实现也必须等下一条消息」、
      「遇到任何错误就停下等指示」、强制的退出模式口令；
- [ ] 确认第二节六个规则点在两份副本里仍然一致；
- [ ] 在本文件第三节记录新的定制或撤销的定制，并注明日期。

## 五、与全局 Skill 的关系

本目录只管项目内的 OpenSpec 工作流。个人级和插件级 Skill（Superpowers 等）装在用户目录下，
不在本仓库维护，也不应为了本项目去改动它们而不留记录。
