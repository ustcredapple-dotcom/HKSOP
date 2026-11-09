# 新元件入库

1. 在独立工作目录准备一个包。用稳定英文 packageId；名称、厂家、型号可以中文。标准和定制使用同一外壳协议，内部参数仍必须如实声明。
2. 填写 package.json，登记 components、kits 或 registeredBoards 的记录。零件描述采购/制造信息；套件引用零件 BOM，保存机械接口、真实光学面、摆放和交互；板型保存真实孔位及版本。
3. 同一器件的多种安装角度使用 common.json 与 variants。公共数据只合并逐字段完全相同的内容；不同底座、接口或真实光学面不能靠旋转示意图替代。
4. 准备 CAD、图纸、俯视图和证据。在 assets 声明本包资源路径、运行目标路径及 SHA256。目标使用 `assets/step/<english>.step`、`assets/drawings/<english>.pdf` 或 `static/topviews/<english>.svg` 等形式。更新内容使用新的目标文件名。
5. 分别写明 display、placement、simulation、procurement、manufacturing 的状态和证据；未验证填待验证，禁止用一个“supported”代替所有能力。
6. 运行 package check 和 package stage。修正契约或资源问题后再 adopt。库在暂存后改变时重新 stage。入库完成后构建独立运行目录，并实查俯视图、摆放、光轴/光高和 BOM。
7. 追加项目日志和验收记录。需要加工时再按制造门槛整理加工包；需要更新原网站或云端时按明确目标执行发布。

package check 只检查包结构；stage 增加全库契约、BOM 和声明资源校验。两者都不代表 CAD、制造或真实光学性能已经通过验收。

完整包结构参考 engine/schemas/hksop-package.schema.json。旧版原协议保存在 engine/schemas/legacy；既有元件参数字段没有被本次迁移静默改写。

最小物料包起点见 engine/templates/component-package。可摆放套件参考 library/standard 中同类器件，保留原协议字段的语义并替换新设计的实际参数。新增记录和资源一起放入一个包即可，不必逐处手改全库大 JSON。

非标准试制元件可以先存入 library/custom/<id>/drafts，保留原协议、CAD 和说明，不登记进 registry.json。这种草稿已经有存放位置，但不算引擎已支持。补齐可运行协议后再执行 stage/adopt；当前可支持的元件仍统一出现在自动生成的 catalog.json。
