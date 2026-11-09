# Onshape 光学元件库交付与验收

本条款是标准光学协议的云端交付要求，自 2026-10-08 起适用于新增或更新的组装件及本次全库上传。目标名称固定为 **光学元件库**；每个需上传的当前组装件 `kitId / configuration / revision` 提供一个可独立插入和移动的完整 Onshape 装配体，全部自制散件另放 **自制散件** 文件夹。自制件归属以记录中的设计/制造来源为依据，不能仅凭上传者、文件夹所有者或 ID 前缀推断。

## 本次上传范围

用户于 2026-10-08 指定：**旧英制柱子不要上传**。本次“光学元件库”排除旧英制柱单件，当前公制组装件中也不得夹带旧英制柱；不将这些历史柱放入 Onshape 历史文件夹。逐条按稳定 ID、实际尺寸/来源及 BOM 核查并在登记保留排除原因，不能仅凭名称筛选或为上传而缩放、改造历史柱。历史本地源和既有审核证据保留。这一范围约束适用于本次标准光学元件库，不能推广成其他项目永远禁止英制器件。

## 正式映射与组织

正式登记为 `/Volumes/ZZLab_001/Wang Junjie/模块化光路/光学元件库_Onshape/registry.json`，格式 `zzlab-onshape-library-registry-v1`。跨机交接保留这份登记及其 SHA，并按实际 NAS 挂载定位；不在工程实例 JSON、`catalog.json` 或未扩展的 schema 中添加云端审计字段。

- 顶层 `target` 记录名称、实际组织类型、文件夹 ID 与可打开链接。本次统一入口为已实查的普通 Student Folder **光学元件库**（`4ad1c0eb856f398d4bf03fa6`），**组装件**子文件夹为 `fc761caab84b0d4e04fa7da5`，**自制散件**子文件夹为已实查的 `aca6e9de7a0df4f3096709ed`。允许根/子文件夹内多个小文档及子文件夹；普通 Folder 不能登记为 Enterprise Project，文档内 tab folder 也不能冒充账号文件夹。每条目独立保存真实 documentId/workspaceId/versionId/elementId/configuration，不强制全库共用一个 documentId。新文档成为有效映射前须实查其库/子文件夹归属，未查只记录 pending。
- `assemblies[]` 以稳定 `kitId` 关联名称、构型、修订和源 record/CAD。库中每个 kit 都需可追踪条目；实际组装件为 `required:true`。仅复用单件定义的 kit、手册参考激光器和历史理想路径用 `required:false`、`excluded/not-applicable` 及真实原因说明，不重复造装配体。需上传但缺完整 CAD/基准的条目保持 `pending`，不能漏列或以占位实体替代。
- `customParts[]` 以稳定 `componentId` 关联每个已注册自制散件及其单件 CAD；没有 component 注册的用户自制异形板使用 `sourceKind:"registeredBoard"` 和原 `boardId`，不能伪造 componentId。有 component 注册的板只复用该 component，避免重复；每条以 componentId/boardId 其中一个真实身份关联。共享散件用同一身份复用，数量仍由每个 kit 的 BOM/occurrence 决定。采购件和标准紧固件按原来源保留在组装件中，不冒充自制件。
- `source` 保存 record 路径/SHA256、目录版本、修订、构型、坐标基准及证据；几何身份使用实际导出 CAD 路径/SHA256，或下述精确冻结的 `nativeGeometryIdentity`。未知字段用 `null` 加原因。`target` 保存实际 `documentId`、`elementId`、冻结 `versionId`、构型及链接；工作区链接仅用于导航，不能代替冻结版本。
- 保留原生 CAD 的原出处；上传本次云端副本不修改原设计，也不宣称 STEP 导入恢复了原生参数化特征。版本更新保留旧冻结来源和删除事实，再登记最新修订及验收证据；按下述用户要求删除被替换的旧云端库副本，不保留其可复用入口。

## 最新上传与更新删除旧库副本

用户明确要求“验收上传最新器件；如果是更新，就直接把旧版本删掉”。新增/更新前读取当前真源 record 和完整 CAD，核对实际修订、SHA、真实构型及制造身份；旧批次文件或旧投影不能冒充最新。首次新增没有额外旧版清理。

更新时先让最新目标完成上传/转换或完整原生复制，核对精确源/目标身份并确认完整当前 Assembly/自制定义可用，再直接删除相同稳定 kit/单件及真实构型中被替换的旧 Assembly/散件 tabs、云端复制文档或旧入口，无需重复确认，不保留可复用的云端历史副本。上传请求成功或只有中间 root 不能作为先删旧库的依据；上传/转换失败或最新定义不完整时保持旧库可用并记录未完成。当前其他组装件共享旧定义时，先重绑并核验它们使用最新定义，再删旧定义；同几何但不同 manufacturingIdentity、不同实际配置不当作旧版删除。

删除回执逐对象记录实际 document/workspace/element ID、对象类型、时间、删除结果和证据；实际删除后旧映射标 `deleted/inactive`、`active:false`、`current:false`，仅保留源 SHA/冻结来源和 deletionIDs 等追溯事实。失败/工具阻断如实留 pending/blocked，不写 deleted。JSON→3D 解析和云端 fallback 都不得再取该旧目标；已有且已验的精确本地冻结来源仍按原规则显式采用。

清理范围是此次库更新产生的旧云端复制对象，不包括用户原始 CAD 文档和其 history。Onshape 的 Main workspace 和版本节点不能删除（[官方版本与历史说明](https://cad.onshape.com/help/Content/Document/versions_and_history.htm)）；可按实际权限删除旧工作区中的 tabs（[官方 Document Tabs 说明](https://cad.onshape.com/help/Content/Document/document_tabs.htm)）或被替换复制文档。平台自动保留的 history 不等于可复用旧库入口；如实记录平台限制，不能声称 history 已清空。

## 保留原生装配的来源身份

采用正常 Onshape 原生复制/粘贴且保留真实内部层级、源 mates 与依赖时，可在旁置登记中用 `source.nativeGeometryIdentity = {documentId, versionId, elementId, configuration}` 作为冻结几何身份，替代不存在的导出文件 CAD SHA。四项必须逐一解析真实源元素与冻结版本；无配置的默认态有实际依据，未知 configuration 的 `null` 仍不作通配。保留精确 source record SHA、目录版本、kit/构型/修订；`cadSha256:null` 写明“采用保留原生装配，未生成该交付的导出文件”等真实原因。已有导出/核验文件的 SHA 仍保留，不能为了采用原生身份丢弃。

仅在该冻结来源的真实几何、柱尺寸及当前自制件、安装/光学基准和旧英制柱排除核查有证据时纳入；名称、复制命令成功或 `nativeOnshapeSources[0]` 不能代替核查。保存原生复制来源、Assembly/Part Studio 外部依赖的文档/版本/元素/构型、mates 与原机构自由度来源、实际目标元素及映射证据。目标仍须冻结真实 version 并逐 kit 完成全部云端验收；来源原生身份不使 pending 自动通过，也不授予修改原设计的权限。

分别登记 `nativeCoordinateFrame` 与每个导出文件的 `cadArtifactCoordinateFrame`，并把真实源 native frame → kit-local 的 `sourceToKit` proper 刚性变换（原点、rotation rows、单位/比例及真实柱轴/底面/安装孔/光学基准证据）绑定到精确源身份。保留原生坐标的复制不能套用已归一 STEP 的坐标或再次应用其变换。目标若改变坐标须另核 target → kit-local；缺 native frame/变换/基准证据时，上传可留待验，自动复用仍为 pending。实际没有玻璃光学面的机械 kit 将相应光学字段保留 null 并说明，以真实制造/安装基准核定机械坐标。

## 当前映射的唯一解析

云端映射以稳定 `kitId`、真实构型身份和冻结来源组成身份键。构型从当前 record 的 `mechanicalConfiguration`、`assemblyPoseRecipe` 或原生 Onshape configuration 读取；无配置的默认态须注明依据，未知 `null` 不作为任意构型通配符。修订优先读取记录已有的 `revision`、`metricRevision.revision`、`manufacturingRevision`、`mechanicalRevision` 或 `manufacturingIdentity`，保留实际字段路径和原值，不从名称或 ID 后缀猜版本。修订名称确实未知时保留 `null/unknown` 与原因；目录版本、record SHA、几何身份（CAD SHA 或精确冻结的 nativeGeometryIdentity）及构型已精确唯一匹配时，仍可登记这个冻结身份，并在验收说明中写明名称未知。

用 `active/current` 标识区分可复用的当前映射、待验候选和历史映射：每个 `kitId`/构型最多一个已验收的当前有效映射；`pending/blocked/failed` 候选不得成为有效映射。更新保留旧来源追溯和实际删除事实；完成最新上传/转换及完整定义可用性核查后删除被替换旧库对象，新条目只有全部必需验收通过才设为当前。解析须精确核对所需目录版本、record SHA、构型，以及采用的唯一几何身份：CAD 文件使用 CAD SHA，保留原生装配使用完整 `nativeGeometryIdentity`（document/version/element/configuration）；不能在 `nativeOnshapeSources` 多条来源中任取第一条，也不能把旧投影证据、较早版本或 `/w/` 导航链接当当前冻结来源。

匹配结果为零或多条时，将受影响 kit 的云端复用记为 `pending`，列明缺失/冲突候选与原因；不按显示名、时间、列表顺序或未知值猜选。可显式回退与所需冻结身份相符且已有验收的本地 CAD；没有这样的本地来源则保留缺证。云端冻结来源与本地回退各自记录采用证据。

## 云端验收清单

源几何预检须核查实际 CAD 内容、层级/名称/几何和来源对应；本地 `cadPath` 存在或原生源链接可打开都不能单独记为预检通过。云端交付完成须逐项有实际证据；上传请求成功、STEP 可读、预览可见或多套打包导入后的中间 root 均不能单独作为完成依据。

| 验收项 | 必须核查的实际结果 |
| --- | --- |
| 上传与转换/原生复制 | 文件路线核查源 SHA 对应文件确已上传且导入转换完成；原生路线核查精确冻结源已完整复制，记录源/目标元素、依赖与 mates 来源，转换项按真实不适用原因登记；两条路线均记录错误、警告及受影响对象 |
| 独立装配体 | 每个 required:true 的当前组装件 kit/构型/修订有独立 Assembly element；目标元素可打开，完整源层级和原名称保留，重复实例有独立 occurrence |
| 层级与 BOM | 反查源/目标子装配、叶件及闭合 solid occurrence 数、零件身份和装配数量，覆盖镜架、转接件、柱、紧固件及有证据的光学件 |
| 内部姿态 | 刚性组件按源姿态锁位；有意可动的位移、旋转或调节机构按原机构语义保留自由度，不能为通过验收永久锁死 |
| 整体移动 | 在云端选择完整器件进行实际小幅移动，再 Undo 并核对恢复；记录覆盖的 kit/构型，不能由一个成功实例推成全库已测 |
| 尺寸与基准 | 单位为 mm、比例 1，安装孔、柱轴、支撑面、真实光学面和局部坐标与冻结来源一致；不通过缩放或包围盒猜测补基准 |
| 版本与引用 | 冻结目标版本，记录 document/element/version/configuration 与源 record SHA、目录版本和采用的几何身份的映射，后续 JSON→3D 能以 kitId 唯一解析当前修订 |
| 自制散件 | 所有纳入本次上传的自制件有可独立复用的单件元素并位于自制散件文件夹，来源、componentId/boardId、版本和图纸关系可追溯 |

`acceptance` 按项目上述维度分别记录实际状态、范围、时间和证据；未执行为 `pending`，工具阻断为 `blocked`，失败为 `failed`，不适用须有依据。所有必需项通过且 ID/冻结版本完整，才可标为云端完成。云端装配验收不替代完整干涉、通光、操作空间、制造放行或实物测试。

本次用户已授权创建该库并上传全部组装件和自制散件；一次工具或安全检查阻断只记录当次未完成状态，不构成后续重试必须重新授权的规则。按正常授权工具恢复操作，保持原设计和已有库版本可追溯。

## JSON→3D 复用

`zzlab-optics-json-to-3d` 建模前先读这份登记，以输入的 `kitId`、构型、目录版本/修订、源 record SHA 和采用的几何身份（CAD SHA 或精确 nativeGeometryIdentity）解析冻结装配体；一个布局实例插入一个完整子装配 occurrence，保留内部层级与实例 ID。自制件从 `componentId` 或原 `boardId` 对应的散件定义复用，不以显示名称合并实体。

映射过期、版本缺失、云端验收未通过或目标库当前受阻时，显式回退到已有且已验收的本地冻结 CAD，并记录采用的来源及云端未完成项；这不阻止有完整来源的本地建模，也不能声称云端复用已完成。安装/光学基准及刚性变换仍须独立核验。

当前 PT1/M 直装例：`stage-board-thorlabs-pt1m` 的 `R2-A7075-DIRECT-MOUNT`（完整 Assembly CAD SHA `f44af11b61f08b62eefb97e0e2288a627f893c864a73199ea3d490dec24bd696`）相对主面包板顶面的台面名义高度为 `20.32 + 17.18 = 37.5 mm`，本构型取消 PT1-B；不能沿用旧 50 mm。JSON→3D 按所选冻结 record 的 `directMounting.nominalTopHeightMm`、完整源总装及该 record 的机械审查证据，逐级核验台面、承载板和上置器件的实际高度链与局部坐标，再计算绝对光高；不将本例高度推广到其他台或修订。本例实物验收仍为 `not-performed`。

