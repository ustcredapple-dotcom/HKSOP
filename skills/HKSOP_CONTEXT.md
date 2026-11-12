# HKSOP-github 工作区上下文

[English](HKSOP_CONTEXT.en.md)

本目录上一级是工作区根目录。业务 skill 在本副本中优先遵守根目录 AGENTS.md、config/distribution.json 和用户当次要求。

当前范围是标准元件及一分三/DoublePass 所需依赖、现用 STEP、俯视资源、配套三视图/加工图/打标文件与三个 JSON 示例。用户于 2026-11-09 明确允许补入现用图纸并直接更新 GitHub；目标为 ustcredapple-dotcom/HKSOP，覆盖此前不含图纸的分发限制。用户随后明确要求仓库公开；public 是当前分发目标，覆盖此前私有限制。

引擎保留当前实现；元件库保留现用定义及 `library/history` 中旧设计依赖。此精选副本不带项目历史；旁边 HKSOP 是完整本机来源，不为适配此副本而修改它。新入库使用 hksop.py package check/stage/adopt 与 catalog build。

旧 skill 的机器绝对路径、历史发布步骤及网站/Onshape 默认同步属于原环境说明，不自动执行。资源按本副本的 resource-map.json 和资产清单定位；不恢复已排除的旧验收或退役英制柱文件。

机械、光学、采购、制造验收分别保留真实状态。图纸恢复、哈希检查和目录整理不等于新的实物或加工验收。目录英文说明用于导航，详细工程参考继续保留原文与已有技术约束。

AI 已验证的设计入库默认直接复用验收，只检查新增、变更及其直接影响的部分。已有资产、证据和事务内构建不重复执行；按 [验收复用规则](zzlab-optics-library/references/acceptance-reuse.md) 保留原验收范围与未完成项。本规则优先于旧 skill 的无差别全项复验要求。

AI 自动设计或修改自制加工件时，执行 [倒 C 角规则](zzlab-modular-optics/references/design-rules.md#chamfer-protocol)：普通去锐默认 C0.3×45°，功能边/薄壁/配合处单独判断，倒角进入实际 CAD/STEP 并与加工图一致；只检查本次变更及直接影响。

元件更新按 [旧设计依赖协议](../docs/component-history.md) 记录当次保留选择：保留时先冻结旧版及必要资料到 `library/history`，明确不保留时跳过本次归档，未说明先确认；旧工程继续解析/渲染，历史元件禁止新拖入/新增。此规则覆盖旧元件只保留当前版及直接删除旧资源的条款。
