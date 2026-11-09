# 解析、复建与验收

## 当前已知输入语义

当前格式为 `format: zzlab-optics-project`、`version: 1`。先检查 `requires` 中的能力，当前 R1 用到 `zzlab-collision-overrides-v1`、`zzlab-metric-supports-v1`；遇到未知格式、版本或能力不要默默忽略。

| 字段 | 对三维建模的含义 |
| --- | --- |
| `metadata.opticalAxisTargetMm` | 目标光高；必须与板高、kit 名义光高及真实光学面核对 |
| `catalogVersion` | 冻结所用目录版本；不是当前库必然仍处于该版本的保证 |
| `layout.baseMode`, `layout.board` | 确定根参考/实体板语义；`table` 模式的根板可仅作桌面参考 |
| `layout.subBoards[]` | 实际板 ID、尺寸、孔阵列、位置与旋转；用 `boardId` 关联实例 |
| `layout.instances[]` | `id`、`kitId`、相对所属板的 `xMm/yMm` 与 `rotationDeg` |
| `board.pitchMm/edgeOffsetMm` | 规则孔阵列，孔心为 `edgeOffsetMm + index × pitchMm` |
| `board.mountingHoles[]` | 指定行列的固定孔选择；具体加工结构仍须制造规格/源几何证明 |
| `optical[instanceId::slotId]` | 该实例光学槽选项；旧 `module:*` 记录不能替代实际实例匹配 |
| `opticalRendering` | 网页光路生成/显示设置；单一 flag 不能证明可生成三维光束 |
| `collisionOverrides[]` | 指定实例对的平面豁免；不是三维无干涉证明 |

核对所有实例、被实际使用的 kit 和所属板；`catalogReferenced` 可含未放置套件，不据此自动加装。`extras`、模块数量或其他扩展若实际影响几何，也须解析其语义和证据，不静默遗漏。

## 光学元件库映射与复用

建模前读取 `/Volumes/ZZLab_001/Wang Junjie/模块化光路/光学元件库_Onshape/registry.json`，确认格式为 `zzlab-onshape-library-registry-v1` 并冻结所用登记 SHA。该登记与 `latest-model.json` 分工：前者登记可复用标准器件及自制散件的云端定义，后者登记本次布局总装的成果位置和状态。

- 本次统一库入口为普通 Student Folder“光学元件库”（`4ad1c0eb856f398d4bf03fa6`），可含多文档及组装件/自制散件子文件夹，不能当 Enterprise Project。各条目使用自身真实 document/workspace/version/element/configuration；新文档实查库归属前保持 pending。上传请求成功而最新完整定义尚不可用时不删除旧库。
- 由输入 `kitId`、构型、目录版本/修订、精确源 record SHA 和几何身份（导出 CAD SHA 或冻结 nativeGeometryIdentity）解析 `assemblies[]`；云端复用必须取得真实 documentId、Assembly elementId、冻结 versionId 和 configuration。一个需上传的当前组装件 kit/构型/修订对应一个完整独立装配体；多套打包导入的中间 root 不能当作每个 kit 的定义。
- 读取各项 `acceptance`，核查上传转换、内部层级与叶/solid occurrence 数、BOM 身份、单位/比例/安装与光学基准、刚性组件锁位及机构自由度、实际整体移动与 Undo、冻结版本映射。不能把有意可动的机构永久锁死，也不能由局部成功推成全库通过。
- `customParts[]` 按真实 `componentId` 复用 **自制散件** 文件夹的单件定义；没有 component 注册的用户自制异形板按 `sourceKind:"registeredBoard"` 与原 `boardId` 解析，不能伪造 componentId，有 component 注册的板不重复登记；按登记核查真实组织类型与文件夹 ID，保留源设计和图纸关系。STEP 云端导入副本不等于原生参数化特征恢复。
- 每个布局实例以一个完整子装配 occurrence 插入，总装中保留实例 ID；重复器件复用冻结定义但不合并 occurrences。基准仍按下节独立核验并建立 proper rigid transform，不能以显示名称或包围盒猜映射。
- `deleted/inactive`、`active:false/current:false` 的旧云端目标禁止解析和云端 fallback；已删目标不得因仍有 version 链接再次成为候选。本地回退仅采用与本次所需精确冻结身份相符且已验的本地 CAD，并保留真实采用证据。
- 目标 ID/冻结版本为空、登记 `blocked/pending`、源 record SHA/几何身份或修订不匹配时，记录受影响 kit 与原因，显式回退已存在且已验收的本地冻结 CAD。保留其真实路径、SHA、修订和采用理由；本地建模可继续，但云端复用状态保持未完成。缺本地源时仍按原缺证规则处理，不补造模型。

本次标准库依 2026-10-08 用户要求排除旧英制柱单件，不将其上传到历史文件夹；解析登记、BOM 和本地回退源时，确认当前公制组装件未夹带旧英制柱。范围外条目保留稳定 ID 与排除原因，历史本地模型/证据不删除；此约束不推广到其他项目的英制器件。

登记覆盖全部 kit，但 `required:false` 的单件复用 kit、手册参考激光器及历史理想路径按真实排除/不适用原因处理，不作为待插入装配体或自动补造器件。`cadPath` 存在不代表源内容/层级/几何预检或云端验收通过，须读取实际来源及验收证据。


解析当前映射时，按 `kitId`、真实构型、冻结目录版本/record SHA 及采用的几何身份（CAD SHA 或完整 nativeGeometryIdentity）精确匹配，检查 `active/current` 标识；每个 kit/构型最多一个已验收的有效当前映射，`pending/blocked/failed` 候选不作有效映射。构型取当前 record 的 `mechanicalConfiguration`、`assemblyPoseRecipe` 或原生 configuration；无配置默认态需有依据，未知 `null` 不作通配。修订从已有 `revision`、`metricRevision.revision`、`manufacturingRevision`、`mechanicalRevision` 或 `manufacturingIdentity` 解析并留字段路径/原值。修订名称确实未知可保持 `null/unknown`，有精确目录版本、record SHA、几何身份与构型的唯一冻结身份仍可使用，但验收须说明名称未知，不从显示名或 ID 后缀猜版本。

保留原生装配时，source 的 `nativeGeometryIdentity = {documentId, versionId, elementId, configuration}` 可替代不存在的导出文件 CAD SHA；精确 record SHA/目录版本/构型仍必需，`cadSha256:null` 写未生成导出文件的真实原因，已有导出或几何核验文件 SHA 不丢弃。仅采用冻结源实际几何、当前柱/自制件、安装/光学基准与旧英制柱排除已核的来源；保存复制依赖、源 mates/机构自由度出处和目标映射证据。未知或零/多匹配保留 pending，原生复制不免逐 kit 云端验收。

分别登记 `nativeCoordinateFrame` 与每个导出文件的 `cadArtifactCoordinateFrame`，并把真实源 native frame → kit-local 的 `sourceToKit` proper 刚性变换（原点、rotation rows、单位/比例及真实柱轴/底面/安装孔/光学基准证据）绑定到精确源身份。保留原生坐标的复制不能套用已归一 STEP 的坐标或再次应用其变换。目标若改变坐标须另核 target → kit-local；缺 native frame/变换/基准证据时，上传可留待验，自动复用仍为 pending。实际没有玻璃光学面的机械 kit 将相应光学字段保留 null 并说明，以真实制造/安装基准核定机械坐标。

原生源和目标均核对实际 document/version/element/configuration；多条 `nativeOnshapeSources` 不任取第一条，旧投影/历史版本与 `/w/` 导航不替代当前冻结源。零条或多条匹配均将受影响 kit 的云端复用记为 `pending`，列明候选/缺证，再显式回退与所需冻结身份相符且已验的本地 CAD；缺这样的本地来源则保留缺证。更新使用当前最新 record/修订及完整 CAD；最新目标上传/转换或原生复制完成、精确身份及完整定义可用且当前共享依赖重绑后，按用户要求直接删除相同稳定身份/真实构型中被替换的旧云端库副本，无需重复确认。不同实际配置或不同 manufacturingIdentity 不作旧版删除。旧映射记录实际 deletionIDs、证据及 deleted/inactive、active:false/current:false，保留源追溯，不能静默替换历史工程来源。平台 Main workspace/版本 history 不可逐条删除，不伪称已清空；用户原始 CAD/history 不属库副本清理范围。

同一用户已授权的库上传因工具阻断而中断时，恢复正常工具后可继续该授权范围；一次故障不增加永久的重复授权要求。目标库和每次布局总装的云端完成状态分别记录。

## 冻结与坐标

在新工作目录冻结输入、kit records、源 CAD、目录版本和 SHA。冻结 `translation_config.json` 中的 CAD 文件、源子组、来源链接、预期叶数、局部原点与 proper rotation rows，并保存各基准的几何证据。基准不能从图像轮廓、`collisionBoundsMm` 或 CAD 总包围盒倒推。

kit 局部系约定：柱/安装基准在 XY 原点，真实底部支撑面 `Z=0`，`+Z` 向上。支撑孔偏移来自 record 且要在源 CAD 验证；真实光学面/光心与 `opticalAxisHeightMm` 交叉核验。先建立 `T_source→kit`，再应用 `T_kit→board`、`T_board→world`，按此顺序复合。板旋转时实例位置和 yaw 都随板变换，不能只给 XY 加偏移；`supportZ` 要按板真实上表面和板的全局位姿计算。

当前 R1 源板为局部 `topZ=0`、`bottomZ=-12.5`；总装板位姿 `(275,87.5,12.5)`，因此板底全局 `Z=0`、器件支撑全局 `Z=12.5`。kit 名义光高 `62.5`，名义光轴全局 `Z=75`。此数值链是这个冻结案例的证据，不是其它板或 kit 的默认值。

## 复建入口的适用边界

从 `latest-model.json` 的 `rebuild` 读取入口与工作参数。当前 `src/build_assemblies.py` 只支持 `baseMode=table`、单一子板、子板 yaw `0`、无 elevation，且冻结为 5 种 kit、18 实例的 R1。脚本的断言是边界，不能删除断言后假称支持其它布局。新输入超出边界时，保留旧版，在新工作副本扩展解析/变换并独立验收。

R2 的 `src/assemble_r2.py` 只适用于新 `-3.json` 与 R1 机械布局不变的本案例：复用冻结的 5 种 kit、18 个实例与板，并加入重新计算的 17 段光束及 7 个零厚名义镜面。它依赖登记的 R1 正式机械母装和完整工作树。若布局、板、光学槽或光源参数改变，必须先重算 trace，扩展受影响的变换/光学表达并重新验收；不能仅套用旧光束。

复建示例（两个目录使用登记的路径，输出须为新目录）：

```sh
'/Users/Shared/ZZLAB/OpticsKits/cad-venv/bin/python' '<登记的 buildEntry>' '<登记的 workDirectory>' '<新输出目录>'
```

先读入口实现与参数，不把此占位示例直接执行。正式包内 `05_复建资料` 也包含入口、冻结 source 与环境记录，可作为完整工作树之外的复建材料；板生成器、预览渲染器和独审脚本按需要读取。

## 导出层级

使用 STEPCAF/XCAF 读取完整树，区分 definition 和 occurrence，累积父位姿与叶位姿并保留名称/颜色。选取 kit 的完整源子组，保留镜架、转接、柱、螺丝、镜片等内部节点；重复叶名称用源 occurrence 标识区分。不要将厂家实体缩放、fuse 或重建；局部归一化优先放在 occurrence placement，避免改写供应商 trimmed surfaces 参数。

每种 kit 先输出独立 STEP 和读回报告，再以其完整定义作为总装 occurrence。顶层为真实板与各实例子装配；读取 STEP 反查此层级，不能只看预览。R1 顶层为 `1 + 18 = 19`；R2 增加一个光束可视化层后为 20。R2 的 7 个零厚名义镜面放在对应器件内部，不增加顶层器件。其它案例从输入及可视化层派生期望数，不硬套 19 或 20。

## 有条件的三维光束渲染

先检查 `opticalRendering` 与实际网页状态，再把已显示光路段对应到真实已装配光学元件及其 optical datum。只有二者均有证据的路段才可进入三维渲染；网页未渲染光路或相应光学件未装配的路段不生成，也不从项目名、源参考镜片或机械占位补猜。

当前输入 `opticalRendering.generated=false`、`visible=true`，没有提供实际光束参数；`visible=true` 只是一项显示设置，不证明光路已经生成和显示。当前 R1 `beamRendering.status=none`。未来输入须重新读取配置并核查前提，不能沿用本次无光线状态作永久禁用。

这是旧 `-2.json` / R1 的结论。新的 `-3.json` 已含实例 `optics`、物理源参数；若保存的生成标志与用户当前网页截图不一致，不能用旧标志否定已显示的光路。用户明确要求按新参数生成时，保存授权和截图，复用已冻结的网页纯计算引擎得到真实坐标、分支和随程束径；不得手绘猜路径。

物理光束粗细用可追溯的 mm/rad 参数：直径/半径及其定义（例如 1/e²）、waist 位置和大小、divergence 或等效传播数据。网页 px 线宽仅是视觉样式，不得当 mm 直径。沿路段按已知传播模型和实际光学元件更新束径；缺参数就向用户获取或登记待补，不生成默认粗光柱并标成真实。显示模型的定义、缺证和误差应留档。

## 验收证据与结论范围

- 解析：实例、kit/板匹配、optical slot 与缺证记录完整；源/输出 SHA 和环境可追溯。
- 几何：读回源及输出的有效性、叶与 solid occurrence 数、位置/bounds、proper rotations；开放 shell 不作为封闭体积积分。
- 安装与光高：实际孔中心/阵列及偏移、板支撑面、每实例 optical datum 的全局值与目标；名义值和实际面测量分开。
- STEP 体积：沿用既定比较阈值，保留误差及 pass/fail；闭合 solid 数、bounds 一致也不证明所有 trim 边界等价。必要时针对供应商周期面/trim 做独立几何对照，未解决则标记布局参考，不制造放行。
- 干涉：保存的 override 对逐组筛查；AABB 可排除明显空间重叠，但不能证明完整布局无实体干涉、通光无遮挡或工具可操作。完整布局验收另留范围、方法和结果。
- 预览与光线：从真实 CAD 渲染俯视/三维；确认光束渲染前提、物理粗细来源和元件对应。不用预览替代几何或云端验收。
- 云端：记录目标文档、上传、import tree、配合、固定板及实际整体移动的实查结果。未做的项保持 false/pending，附工具阻断证据。

Onshape 导入完成后，在总装反查完整器件数量与内部锁位；仅对按源语义应保持刚性的内部组使用 `Lock/follow position to → Lock current`；有意可动的机构保留对应自由度，面包板另行 `Fix`。按实际保存状态反查菜单，不把“命令已点击”当保存成功。选择完整器件后，用自由拖动或 triad 做小幅移动，再 Undo 并确认原布局恢复，记录实际覆盖的器件类型；不能由一个实例推成全部实例逐个实测。开放光束面要核查是否导入及可见，必要时在云端设置绿色外观，尺寸比例保持 1。操作语义见 [Onshape 实例列表](https://cad.onshape.com/help/Content/Assembly/instances_list.htm) 与 [triad 操纵器](https://cad.onshape.com/help/Content/Home/triad_manipulator.htm)。

输出至少有独立子装配、板、总装 STEP、位置清单、冻结复建资料、验收记录和 SHA。ZIP 校验 CRC/成员 SHA、目标 NAS 回读和迁移回执完成后，才能将迁移状态改为 `verified`。模型是否可用于制造、云端是否完成是独立状态。

## 最新模型登记的维护规则

`latest-model.json` 是位置与状态的唯一登记，不在正文另维护一套最新路径。

- `latestModelId` 指向 `models[].id`；追加版本后保留原记录及 SHA。没有验收的新结果不可冒充已验收版本；可作为新的最新记录但必须清楚保留其未完成状态。
- `paths` 放正式 NAS 输出与完整工作树；`rebuild` 引用该版本冻结入口，不引用将清理的本机生成目录。
- `artifacts` 保存主 STEP、ZIP、输入等 SHA；`acceptance` 指向原验收并保存关键范围和结论；`onshape`、`beamRendering` 保留实查事实及缺证。
- 同一记录进展更新当前状态，并追加 `statusHistory`；不能抹去原失败、pending、限制或来源 SHA。迁移回读尚未完成时用 `migrationStatus: pending`，同时说明已核验范围。
- 更新前读现有登记；确认文件、SHA、验收和日志中的实际证据，再原子写回并解析校验。不因未来路径已声明就把迁移标为完成。

## confocal R1 公制选柱与旋转位移台案例

`xbk-confocal-hierarchical-R1-20261009` 使用该版本登记的 `src/build_confocal.py --work ... --out ...`，只绑定冻结 `-5.json` 的18实例/12种kit。缺省根板模式按冻结网页语义解析为breadboard；真实根板底世界Z0、顶Z12.5。PT1/M与MT1/M分别yaw270/90，顶板和payload通过真实安装孔/支撑面复合，目标100mm光高从根板顶计，名义世界Z112.5。原R1/R2单子板入口不能替代本入口。

换柱不是伸缩厂家件：原柱节点由完整真实face/edge/vertex几何唯一proper rigid匹配；选择现行公制柱原始CAD、保留其clocking placement。经真实低面筛查无已建底座安装bolt的kit，所有非柱上部叶沿kit+Z平移高度差；有底座固定件的新来源须重新审计。原厂B-rep只改变occurrence位姿，不重造、不缩放。各source/export坐标身份单独绑定，已归一源不得再次套旧native→kit变换。

本案例19顶层是16rootkit+2STAGE_SYSTEM+1根板，2个物镜kit在各stage_system内，总18套。每台厂家源以64-solid复合叶保留，无已验固定/移动分组或运动mates，只能记录q=0参考，不能通过LockCurrent整个stage假称行程已还原。来源缺光学玻璃面/腔镜/光源时不补造；本JSON缺物理beam参数，三维无光束。

新STEP转移体积通过不解除fiber来源原严格体积失败。21个厂家variant叶的严格辅助face/edge配对失败单列保留；独审的全边界vertex摆位、新柱真实底顶轴与孔通过只证明本范围位置/高度。preview中PD有1个原面未生显示三角网格，源B-rep未改。完整trim等价、干涉、光路、机构运动与制造放行均须另有证据。
