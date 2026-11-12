# 新元件入库

[English](component-intake.en.md)

1. 在独立工作目录准备一个包。用稳定英文 packageId；名称、厂家、型号可以中文。标准和定制使用同一外壳协议，内部参数仍必须如实声明。
2. 填写 package.json，登记 components、kits 或 registeredBoards 的记录。零件描述采购/制造信息；套件引用零件 BOM，保存机械接口、真实光学面、摆放和交互；板型保存真实孔位及版本。
3. 同一器件的多种安装角度使用 common.json 与 variants。公共数据只合并逐字段完全相同的内容；不同底座、接口或真实光学面不能靠旋转示意图替代。
4. 准备 CAD、图纸、俯视图和证据。在 assets 声明本包资源路径、运行目标路径及 SHA256。目标使用 `assets/step/<english>.step`、`assets/drawings/<english>.pdf` 或 `static/topviews/<english>.svg` 等形式。更新内容使用新的目标文件名。
5. 分别写明 display、placement、simulation、procurement、manufacturing 的状态和证据；未验证填待验证，禁止用一个“supported”代替所有能力。
6. 运行 package check 和 package stage。修正契约或资源问题后再 adopt。库在暂存后改变时重新 stage。复用事务已完成的校验与运行目录构建，仅补缺少的构建及新增/变更记录尚未覆盖的资源、摆放、光学基准和 BOM 映射检查。
7. 追加项目日志和验收记录。需要加工时再按制造门槛整理加工包；需要更新原网站或云端时按明确目标执行发布。

package check 只检查包结构；stage 增加全库契约、BOM 和声明资源校验。两者都不代表 CAD、制造或真实光学性能已经通过验收。

完整包结构参考 engine/schemas/hksop-package.schema.json。旧版原协议保存在 engine/schemas/legacy；既有元件参数字段没有被本次迁移静默改写。

最小物料包起点见 engine/templates/component-package。可摆放套件参考 library/standard 中同类器件，保留原协议字段的语义并替换新设计的实际参数。新增记录和资源一起放入一个包即可，不必逐处手改全库大 JSON。

非标准试制元件可以先存入 library/custom/<id>/drafts，保留原协议、CAD 和说明，不登记进 registry.json。这种草稿已经有存放位置，但不算引擎已支持。补齐可运行协议后再执行 stage/adopt；当前可支持的元件仍统一出现在自动生成的 catalog.json。

## 复用已有 AI 设计验收（用户约定，2026-11-09）

AI 已经验证过的设计直接复用原验收，只检查新增、变更及其直接影响的部分；普通入库默认适用，无需另选“简化模式”。已有模型、BOM、图纸、俯视图、文件哈希和验证记录直接使用，不重新测量、重画、渲染或逐页复看。

读取当前回执/清单，确认修订与输入身份，补缺少的入库字段和资源，执行 check → stage → adopt，仅检查新增/变更入库映射和未覆盖的运行行为。事务已完成的校验与构建直接复用；不再追加全库回归、整套 CAD 或重复浏览器流程。内容变化、依赖不兼容、证据缺项或矛盾只触发对应部分的检查。

日志只需注明沿用来源/版本、此次变更、实际补做检查和未完成项。名义几何、实物试装、全调角行程、制造放行和云端同步保留各自原状态。详见 [验收复用与最小入库流程](../skills/zzlab-optics-library/references/acceptance-reuse.md)。

## 更新现有元件时保留旧设计依赖

采用新版前，按 [旧设计依赖协议](component-history.md) 记录用户当次“保留历史/不保留”选择；未说明先确认。选择保留时，保存旧定义、CAD/图纸/渲染及必要BOM依赖到 `library/history`，核对版本身份和引用完整性；明确不保留时跳过本次归档。不能仅因当前目录不再引用就删除旧资源。历史实例仍可打开/渲染，但历史元件不能出现在新建拖入列表或绕过新增检查。仅补变更相关的兼容性验收。
