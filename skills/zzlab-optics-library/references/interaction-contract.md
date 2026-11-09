# ZZLab 元件导入与交互设定协议

协议编号：`zzlab-optics-interaction-contract`；协议版本：`1.0.0`；核对日期：2026-10-05（Asia/Hong_Kong）；运行目录基线：`catalog.version = 2026-10-05.5`。

本文件是交给其他 AI 的实施与验收约束。下文“必须”描述本协议要求；“当前实现”描述已逐项查阅的代码行为。协议资料、证据、验收记录放入旁置档案，**不要把本文件新定义的审计字段直接注入工程 JSON**；工程解析器会拒绝未知字段。文件路径以应用源码根目录为基准。

## 1. 对象身份：不能把所有东西都叫 component

| 对象 | 当前权威位置 / 主键 | 语义与允许操作 |
|---|---|---|
| 制造或采购条目 | `catalog.components[]` / `id` | `kind` 为 `custom`、`lubang`、`standard`。这是 BOM 和文件交付项；有 STEP 不等于能拖进画布。 |
| 可选择套件 | `catalog.kits[]` / `id` | `components[]` 定义每套用量；`layout` 定义俯视图、安装、碰撞、光学基准；`opticalSlots[]` 定义可选光学片。套件可能只供整套采购，`placementAllowed:false` 时不能摆放。 |
| 画布实例 | `layout.instances[]` / 工程内唯一 `id` | 通过 `kitId` 引用套件；保存位置、朝向、所属小板、垫高、换柱、光学设置。实例不得覆盖目录里的模型路径、尺寸、材料或采购组成。 |
| 参数面包板 | `layout.board` 或 `subBoards[].board` | 由合法尺寸、孔阵和固定孔生成 STEP/PDF；派生文件身份按参数及制造策略计算。 |
| 登记异形板 | `catalog.registeredBoards[]` / `id + revision` | 已核对的真实轮廓、开窗、实际孔和文件。工程只保存 `registeredBoardId`、`registeredBoardRevision` 及固定孔选择，不能用参数框重新造形或改孔。 |
| 小板模块 | `layout.subBoards[]` / 唯一 `id` | 板体加 `boardId` 指向它的全部实例。在同一画布整组移动、旋转、复制；右键或双击进入内部编辑。不是另一个独立总览。 |
| 共享套件 | `shared_kits.py` 的工程快照 / 服务端 `id` | 命名并发布的一份不可变工程快照，可重新装入、下载；撤下与恢复可逆。发布不直接变更可信 catalog。 |
| 独立完整模块数量 | 工程 `moduleQuantities` | 用于 DP、一分三等整套清单；数量并不包含布局坐标，不能凭它恢复画布。 |

源：`layout.py::validate_layout`，`stacked_layout.py::validate_stacked`，`registered_boards.py::normalize`，`shared_kits.py::project_payload/publish`，`static/project-file.js::normalize/create/parse`。

## 2. 坐标、机械基准和俯视图必须绑定

1. 全部真实几何单位为 mm；板坐标原点在左下，X 向右、Y 向上。世界 Z=0 是根板顶面；根板自身厚度不计入器件相对根板的光高。
2. 实例 `(xMm,yMm)` 是已登记安装锚点位置，**不是图片包围盒中心，也不一定是螺孔**。局部轮廓、安装孔、光口、光学中心均相对该锚点。`baseBoundsMm` 的中点用于双击测量的底座安装中心。
3. `widthMm/heightMm` 与 `anchorXMm/anchorYMm` 描述俯视图图框及图内锚点；SVG 显示 Y 向下，运行画布负责翻转。导入者必须用图像、真实安装孔、底座、光学面共同核对四个朝向，不能靠平移图片掩盖锚点错误。
4. `rotationDeg` 仅为 0、90、180、270，物理坐标逆时针为正：`Rθ(x,y)=(cosθ·x−sinθ·y, sinθ·x+cosθ·y)`。小板实例先变换到小板局部，再随小板变换到根板；方向也只叠加一次。
5. `opticalCenterMm` 是光学面基准；`opticalSurfaceAngleDeg` 是**平面在俯视图里的切线角**，不是法线角。激光光口用 `opticalPortsMm` 的坐标和方向。不得把光学面中心换成安装锚点来修复追迹，也不得移动螺孔来迁就光学中心。
6. 反射镜实际反射面应由“真实后挡/接触面 + 镜厚 × 朝外单位法线”求出。本轮核验镜厚为 0.5 inch 3 mm、1 inch 6 mm、2 inch 12 mm；用户指定偏差不超过 0.5 mm 时保留设计。该 0.5 mm **不是**安装孔吸附容差、等高容差或所有 CAD 的通用公差。
7. 未知尺寸或基准必须保留未知。可登记资料缩略图但 `placementAllowed:false`；已有可靠机身尺寸而安装孔未知，可声明桌面布局可用、面包板安装未确认。光口位置或光高未知时不得用装配中心虚构出光。

源：`layout.py::transform_point/kit_geometry`；`static/layout.js::render`；`static/measurement.js::center`；`static/optical-renderer.js::sceneFor`；目录 `opticalGeometryEvidence`。最近镜面修正证据见 `data_evidence/mirror-plane-2026-10-05/after-audit.json`。

## 3. 拖放和孔位配合

- 安装孔必须登记在 `mountingHoleOffsetsMm`，每孔只含有限数字 `xMm/yMm`；同一坐标只算一个孔。`minimumAlignedMountingHoles` 缺省要求全部；明确填写时要求 1–128 个不同孔。
- 拖动/旋转优先寻找能让**最多真实安装孔**对齐板孔的二维相位，再在同数量方案中选离鼠标最近的位置。不得一律把实例中心吸附到孔上。普通柱底四孔位于 ±12.5 mm 时，在 25 mm 孔阵上中心可以落在孔间。
- 多选拖动采用一个公共位移，保留组内相对坐标。不能分别给每个成员重新吸附导致变形；没有全组兼容解时保留整体关系并显示安装问题。
- 不以“孔距必须相等”拒绝导入。最终判定是旋转后实际孔重合及最少可用数量。实体承载大板当前只支持 12.5/25 mm 的 M6 通螺纹孔；两者互相叠装可以成立，但并非任意摆放都兼容。
- 激光器最少孔数来自该型号目录，不是一刀切。308 nm、532 nm 当前为至少两孔；不能把这个最低门槛复制给未知安装资料的激光器。
- 几何吸附和前后端配合判定主要使用 `1e-5 mm` 数值 epsilon；这是计算容差，不是制造能力或承载能力验证。

源：`static/layout.js::anchorGrid/snap/commonDelta`；`layout.py::mounting_alignment`；`registered_boards.py::aligned`；`static/registered-boards.js`；`stacked_layout.py::aligned`。

## 4. 碰撞、板边界、孔遮挡

| 数据 / 视觉 | 必须保持的语义 |
|---|---|
| `collisionPolygonsMm` / 棕色虚线 | 真实俯视实体轮廓，可以分多个片区。两个片区相交或接触即判碰撞。缺少细轮廓时程序退化为 `collisionBoundsMm` 矩形，可能过于保守；新导入必须尽量提供细轮廓。 |
| `baseBoundsMm` / 蓝色底座线 | 只控制底座是否在板内；上部可悬出。不额外扩大沉孔遮挡区。当前普通器件底座还是矩形边界，异形底座若只用大矩形须明确保守性。 |
| 孔遮挡 | **沉孔圆面范围**与棕色实体轮廓相交即遮挡，不只看孔心。底座线、安装参考圈不产生隐藏的遮挡区。 |
| 绿色选中外框 | 仅为 UI 选择状态，不能当成碰撞、孔遮挡或制造边界。 |

当前碰撞是二维俯视检查，跨小板也检查，不因两个实体实际 Z 高度不同而自动放行。不是完整三维干涉/工具可达性计算。棕色轮廓如果已经加过 CAD 投影安全余量，要把余量及来源记入证据，不能在运行代码再悄悄膨胀一次。

源：`layout.py::collision_polygons/world_geometry/shapes_touch/hole_obstructs_shape`；`static/collision-engine.js::compile`；`static/layout.css`。

## 5. 面包板、4/8 孔和桌子模式

### 参数板

当前边长 25–3000 mm、板厚 3–50 mm、每板最多 2500 孔。M6×1.00 通螺纹在 STEP 中用 Ø5 底孔表示，不建螺旋牙；另可用普通通孔。首孔边距及孔距必须满足 `breadboard.py::normalize_board`。

固定沉孔是 M6 内六角圆柱头用圆柱沉孔：Ø6.6 通孔、顶面 Ø11 深 6.5 mm；板厚至少 8.5 mm；沉孔中心到板边至少 7.5 mm；沉孔与普通孔保留 2 mm 净距；**沉孔与沉孔无 2 mm 净距要求，但不能重叠**。这些加工条件仍须校验，不能因为“不都装螺丝”而删掉实体几何检查。

孔选择只能为空、4 孔或 8 孔。存储 `columnIndex/rowIndex` 从 0 开始；界面奇偶从左下第 1 列、第 1 行开始。`rowParity/columnParity=any|odd|even`。

- 4 孔：自动选靠四角、无遮挡且任意两孔 X/Y 坐标差各为 25 mm 整数倍的一组；手动每次点击有效孔，选满后显式应用。
- 8 孔：行列奇偶均相反的两组，每组 4 孔；每组内部遵守 25 mm 规则，组间无需 25 mm。并非任意八孔。
- 选孔响应先作为候选，成功且用户应用后才替换原孔；移动器件不偷偷挪已加工孔，遮挡或失配时提示重新选。

### 大小板

当前仅支持根板加一层小板，最多 24 小板、整份工程最多 500 实例；不支持任意递归嵌套。小板内部实例保存本地坐标，移动板体不重写每个实例。根板可直接接收光学元件，与模块处于同一画布。

实体根板上小板须整体在板内、与其他小板不重叠，并至少存在真实孔重合。4 孔方案要求固定孔全部对齐且无遮挡；小板 8 孔方案只要求至少 4 个对齐且无遮挡，其余保留备用；登记板则用该板的 `minimumAlignedMountingHoles`。承载板已经改为沉孔的位置不能作为有效 M6 固定螺孔。

手动选小板 4 孔时不能选择未重合孔。8 孔模式允许备用孔未对齐，最终四孔最低条件仍须通过。自动八孔会尝试把其中一组四孔对齐，另组保留无遮挡备用。

### 桌子 / 无大板

`layout.baseMode="table"` 表示根 `board` 仅为参考工作区：可自定尺寸，根网格不是实物螺孔，购物车及 ZIP **不生产根板**；小板和器件照常计入。根孔对齐要求关闭，板边界、实体碰撞、小板内部安装、光学等高仍有意义。旧工程省略 `baseMode` 保持实体大板。

桌子工程不能“连同根板”装入成一块虚构小板；可以只导入器件。当前根工作区仍要经过普通 `board` 参数解析，因此并非无限画布。

### 登记异形板

必须用已登记轮廓、开窗和实际孔，不能把被抑制特征未经核对就当成已加工。`holesMm.type` 为 `thread/clearance/counterbore`；M6 可安装螺孔须真实登记 `thread=M6x1.0`。选固定孔只能引用该版本已登记的间隙孔或沉孔 ID，不能在浏览器把普通螺孔临时声称为已加工沉孔。版本不同阻止沿用旧孔位，需要重新登记/装入。

源：`breadboard.py::_normalize_mounting_holes/board_specs`；`layout.py::choose_mounting_holes/choose_registered_mounting`；`stacked_layout.py::validate_stacked/choose_stacked`；`static/stacked-boards.js::editModule/manualMountingSetError`；`static/table-mode.js::setBaseMode`；`registered_boards.py::validate_catalog_boards/normalize`。

## 6. 光高、换柱、垫高、激光垫板

有效光高 = 器件已登记光高 + 器件额外垫高 + 已解析换柱高差 + 所属小板厚度 + 小板垫高 + 已启用激光垫板厚度；根板厚度不再重复计入。未知保持 `null`，不能当 0。

当前自动目标为“已知最高光轴向上取整到 **12.5 mm 倍数**”；不是原来的整 inch，也不能把目录实测 63.5 直接批量改成 62.5。未完成转接件迁移的实际几何光高保持原值。

- 小板垫高使用目录中的麓邦 Ø25 mm 无基座、顶部 M6 螺孔接杆，再使用 OP1 系列垫片；按高规格优先整除，以 0.1 mm 整数单位运算。末尾 0.1–0.9 mm 生成一片相应厚度“精密调整片”列入其他外购件，型号待确认，不能统一塞入 0.4 mm。
- 直接放在根板且拥有登记万能柱的套件优先换柱；以 `universalPostSelection` 显式原柱→目标柱，或在同系列找精确高度。整套所有柱必须改变相同高度；找不到规格则报错，不悄悄用 OP1 补齐，也不宣称目标光高已实现。未换柱保留原 BOM。
- 子板实例显式选柱保留；没有选柱时其额外垫高仍走额外支撑材料路线。支撑点数量可手填 1–128，缺省按板固定孔或器件最少安装孔规则计算；BOM 乘实际支撑点数。
- 服务端全局已知光高不等（差大于数值 epsilon）会产生布局问题；光线遇器件时的光高容差另为 **0.1 mm**。两者现有判据不同，不可在交接时合并成一个数字。多面三维整装不参与单一全局光高比较，按真实各平面追迹。
- 当前自动“光轴对齐垫板”**只支持 308 nm**；固定外形 543×261 mm、厚 8.5–50 mm。4×M6 通螺纹安装激光器，4 个圆柱沉孔接板；沉孔允许藏在激光器机身下，仍须避开激光器安装螺纹孔及承接板已改沉孔。四沉孔按 25 mm 相位取四角。绝对孔组基准未实测必须保持审核版状态。
- 激光垫板当前不支持登记异形板自动制造，不能把规则孔阵计算结果写入异形板制造文件。

源：`elevation.py::automatic_axis_target/universal_post_plan/apply_post_validation/decompose_height/elevation_accessories`；`static/elevation.js::analyze`；`laser_adapter.py::normalize_settings/choose_board_holes/derive_adapter`。

## 7. 选择、复制、属性、测量和画布稳定性

| 操作 | 必须保持的结果 |
|---|---|
| 普通选择 | 单击单选；Ctrl/⌘/Shift 点击增减；Shift 空白拖框；空白拖动平移；Esc 清选择或退出当前模式。 |
| 成组操作 | Ctrl/⌘ A 全选当前编辑板实例；C/V/D 复制、粘贴、复制一份；Delete/Backspace 删所选；已选成员拖动整组；方向键整体移一格；普通组旋转仅单选。 |
| 复制数据 | 冻结复制瞬间的实例、光学参数、光学安装位及实例配件，生成新 ID；粘贴保留相对关系；副本嵌套 source/waveplates/internalOptics 必须深拷贝；全局和按套件配件配置不重复倍增。 |
| 小板模块 | 整体拖动/旋转/复制/删除；右键或双击编辑内部；返回大板继续放别的元件。当前不是多个小板混合框选后任意成组变换。 |
| 撤销 | 一次组拖、删除、粘贴、参数提交作为一个原子动作；几何与选配一起恢复，不能留下孤立采购键。 |
| 测量 | 左键选最近有效点；附近优先光经过的螺孔（局部不超过约 0.75 孔距），否则最近合法螺孔，无“未命中”噪声。双击元件选底座安装中心 A/B；混合孔/中心测量也可。 |
| 测量右键 | 展开该元件属性，不改变 A/B；测量模式禁止 Delete、Backspace、方向键误改布局。 |
| 测量结果 | 报根板坐标 X/Y 距离与方向；只有真实光经过才报累计折线路程，分支和重复经过分列。通孔、沉孔、被子板覆盖的下层螺孔不作为普通测量点；桌面格点标明只是参考。 |
| 面板 | 测量/光束读数是画布内部右下浮层，可拖动、收起，内容增减不推挤主画布；侧边库/参数/清单可收起。浮窗位置是浏览器偏好，不是 CAD 基准。 |

键盘拦截限画布上下文，不能抢走输入框或文本选择的复制删除操作。测量点是临时状态，不写工程或撤销历史；实例位置变化后的读数重新从合法引用计算。

源：`static/layout.js::selectionPacket/commonDelta/removeIds/handleKeydown`；`static/stacked-boards.js::copyModule/pasteModule/editModule`；`static/measurement.js::measureDoubleClick/measureContextMenu`；`static/optical-hole-probe.js::build/nearestValid/snap`；`static/canvas-workspace.js::mountFloatingReadouts`。

## 8. 光学交互数据：机械、模拟、采购三层不能混写

新套件必须**明确**登记 `layout.opticalType`，不要依赖类别名称猜测。支持类型：`empty/mirror/dichroic/pbs/waveplate/lens/coupler/source/unsupported`。`unsupported` 表示可布局但不支持模拟，遇光暂停并说明；`empty` 是已确认没有光学片的空架直通。

实例模拟配置放 `instance.optics`，至少包含 `elementType` 与布尔 `inserted`。可用字段：

| 组 | 字段与约束 |
|---|---|
| 公共 | `configured`、`surfaceAngleDeg`、`clearApertureMm`；未确认装片不能自动当作空架。 |
| PBS | `pbsHandedness=left|right`；修改晶体光学切线手性，不改机械外形。当前按理想 P 透射/S 反射，不是任意用户输入的经验分光比。 |
| 单/多波片 | `fastAxisDeg/retardanceDeg/designWavelengthNm`；`waveplates[]` 最多 8 片，每片独立 `inserted` 和上述三项；数组顺序是正向物理顺序，回程反序并换快轴基。 |
| 透镜 | `focalLengthMm=null` 未配置；非零有限值允许负透镜；不得仅凭产品名推断焦距。 |
| 光源 | `source.enabled` 绑定出光角色；`directionAngleDeg/wavelengthNm/powerMw/beamDiameterMm/beamQualityM2/polarizationType/polarizationAngleDeg/ellipticityDeg/wavefrontRadiusMm`。耦合头未启用出光时为接收端，但须满足入射方向。 |
| 镜面 | `mirror={mode:"ideal"|"data",model,samples}`；样本明确波长、入射角、`reflectanceP/S` 0–1、`phaseDifferenceDeg`，缺值是 null；每实例最多 256 样本；目录大表不复制到每个实例。 |
| 双色镜 | `dichroic.mode="data"`；增加 `transmittanceP/S` 及反射/透射相位差。每个偏振 R+T 不能大于 1。 |
| 三维整装 | `instance.internalOptics[nodeId]` 只引用已登记内部面，类型与源节点一致；镀膜面 `coatingFaceIndex=0|1|null`；不能擅加内部光源。机械位置来自 `layout.opticalAssembly`，不是实例上传的坐标。 |

采购安装位另存工程 `optical[instanceId::slotId]`（完整模块用 `module:kitId::slotId`），包括型号、名称、供应商、波长、插入状态、数量等。模拟不代替 BOM。右键保存安装和模拟应是同一撤销动作；换镜片型号清除旧镜片系数；已存在的手动模拟参数不被目录缺省无提示覆盖。

`inserted:true` 且未填型号：生成待选采购项；`inserted:false`：明确移除，旧型号不得继续采购。带 `replacesComponentId` 的原装光学件须扣除避免重复；物镜整装的 `defaultExisting` 原片存在与“另购替换片”是两件事。耦合头设置为出光，不代表要自动买光纤或透镜。

新激光器必须给每项出光缺省写报告来源和“实测/报告/推导近似/未知”分类。`sourceReport.applyFields` 只允许真实有据字段；点击“采用报告参数”保留原出光开关及未有报告依据的偏振角。M² 报告束腰若无窗面基准不能冒充出光窗口位置；不把消光比推成完整 Stokes。

源：`optics_settings.py::normalize_optics/normalize_internal_fields`；`static/optical-renderer.js::configFor/bindMirror/sceneFor/sourceReportKeys/setInstanceOptics/changeMirrorModel`；`static/project-file.js::opticsFields/internalOpticsFields`；`bom.py` 的安装位解析。

## 9. 光路计算和显示的边界

- 默认一键自动渲染；按批次每帧最多 8 次事件、约 8 ms 让出界面。逐步检查仍保留；进小板先在板边界暂停，再按内部器件继续。Double pass 每次到达独立记录，不用全局“该器件已经渲染过”跳过。
- 默认上限：每束 256 步、总 2048 段、128 分支、累计 1,000,000 mm、最低功率 1e-12 mW。触限给出定位/环路提示，不能无限递归。
- 右键回退选择“第几次到达 + 分支 + 距离”，恢复到该次作用前；当前为全局事件时间线截断，连其他光源在该时刻之后的事件也撤回，不是只删一条光线。
- 移动器件/小板、改上游波片或 PBS 手性后重新求交和传播；拖动时延迟，释放后再更新。仍可连通的路径保留，断路报告位置。退出渲染模式不清光线；显隐独立。光线关闭时不读隐藏光束测量。
- 波长 380–780 nm 用连续示意色；紫外紫色、红外玫红并明确是示意。波长在反射、PBS、波片和薄透镜中不变。线宽随相对源功率温和变化，真实光斑包络按 q 参数，不能用功率直接缩光斑。
- Gaussian 近轴模型：`q'=q+d`；薄透镜 `1/q'=1/q−1/f`；光斑按 1/e² 强度直径，M² 参与。显示有限束腰/焦点；不宣称处理像差、干涉、截光衍射、非圆对称完整束传播或实际光纤耦合效率。
- PBS：`T=(1+S1)/2`、`R=(1−S1)/2`；线偏振为 cos²θ/sin²θ；不是厂家有限消光比与损耗模型。
- 反射镜：使用匹配型号、波长、实际入射角的 P/S 强度反射率及有符号相位差。目录曲线只使用精确有效原表点，不插值、外推或强夹异常值。相位未知且该入射态依赖 P/S 相干项时暂停；纯 P、纯 S 等相位无关情况可算。显式 `ideal` 是近似，不能冒充厂家真实镀膜。
- 偏振约定：时间因子 `exp(-iωt)`，局部右手 `(P,S,k)`，S 沿板法向、P=S×k；`S1=|Ep|²−|Es|²`，`S2=2Re(EpEs*)`，`S3=−2Im(EpEs*)`。相位差为 `arg(rp)−arg(rs)`。理想镜面取 Rp=Rs=1、δ=180°用于基变换，不能等同厂家“零相位”字样。
- 双波片反求：使用选定分支/经过次数的真实入射 Stokes、两片当前延迟、设计波长与目标偏振，求实际物理旋转架两个角。拒绝未装两片、波长不符、不可达目标、偏振度不可能改变。若该次入射已经受同一双波片先前通行影响，当前拒绝固定输入反求；需要全光路反馈求解，尚未实现。
- 多面物镜整装使用三维有限圆面和真实高度，侧视交互不能把竖直段伪造成水平段，也不把竖直段计入板孔测量；未知物镜焦距/NA 只追到机械入口，不假造焦点。
- 沿光路距离为几何折线累计，不是折射率加权光程；同架双波片当前视为同一平面，未加入未知片间距离。

源：`static/optical-engine.js::createSession/advancePending/autoAdvance/rewind/rebaseConfirmed/applyMirror/splitPBS/applyWaveplateSequence/solveTwoWaveplates`；`static/optical-renderer.js::runOpticalToEnd/drawOptics/rewindOpticalTo`；`static/optical-assembly-engine.js`；`static/objective-sideview.js`。

## 10. 工程保存、共享、购物车与权限

工程格式 `format:"zzlab-optics-project", version:1`，扩展名 `.zzoptics.json`，UTF-8，最大 8 MiB。它保存配置，不嵌入资产或追迹快照。目录版本不同提示重核，加载时使用当前可信目录；未知字段、重号、无效引用、非有限数拒绝。解析完整成功后原子替换，失败保留旧画布。

保存 `layout`、原始 `optical`、`extras`、`moduleQuantities`、元信息和 UI 基本状态；实例里的 `optics/internalOptics`、板和元件垫高、`universalPostSelection`、`laserAdapter` 同时往返。`opticalRendering.generated/visible/autoRestore` 保存偏好；不保存光线坐标、已点到哪里、焦点和已算偏振。打开工程按有效参数重新追迹。旧工程缺少字段保持旧行为，不悄悄“升级”采购组成。

共享发布保存工程快照和署名；用户下载/重新装入后各自编辑。装入共享模块时孔位检查、光高、采购映射与普通工程相同；不得允许共享快照覆盖目录资产路径或制造规格。

购物车与画布平行，按账号绑定到服务端数据库：清空画布不能清购物车。加入时保存来源方案快照和贡献数量；修改数量、勾选、移除只影响购物车订单行，不回改原套件或画布。删除优先：`selected = selected && !removed`。导出只取已勾选且未删除项。更新带 `cartId+revision`，同请求幂等；版本冲突要求重载，不能覆盖其他页刚改的车。

生产项的 STEP/PDF/DXF 只由可信目录或服务端参数生成器解析；旧购物车制造路径与当前目录不一致时拒绝作为任意历史文件下载。注册板同时核对版本。导出保留材料/表面处理；小板/垫片/换柱用量按服务端重算。

麓邦导出格式服从现有模板实现。仅明确定义的合法型号进入可导入页；原装配别名/导入尾缀待核对、型号未知进入待核对，不得随意剥 `-1`。此检查只保证声明型号语法与已知疑点，并不保证麓邦当前在售/有库存。

| 身份 | 当前权限 |
|---|---|
| guest | 受管理员 `guestAccessEnabled` 控制进入；可本地编辑、预览、下载清单及工程；没有账号购物车、不能共享发布/撤下/恢复。 |
| guest 制造下载 | 另由 `guestManufacturingDownloadsEnabled` 控制，且总 guest 访问开关也必须开。关闭禁止 STEP/图纸/包含制造资产的 ZIP；不能只隐藏按钮，服务端每请求都检查。 |
| readonly 有完整账号 | 可使用自己的购物车、编辑方案和下载；不能共享发布/撤下/恢复。 |
| user/admin | 可编辑及使用购物车、发布；共享撤下/恢复按所有者/管理员权限；只有 admin 改游客策略。 |

身份须来自现有受信反代，不能导入元件时自行伪造 X-ZZLAB 身份头。POST 同源检查、静态文件白名单、资产路径校验必须继续有效。QA 用隔离数据库和测试工程，不写真实用户购物车/共享库/管理员开关。

源：`static/project-file.js::create/parse`；`shared_kits.py::prepare_project`；`cart.py::require_identity/assert_revision/add/update/export_preview`；`bom.py::lubang_import_plan`；`app.py::authenticate/allow_limited_route/check_origin/require_manufacturing_download`；`access_settings.py`。

## 11. 每次导入的交互验收清单

对每个新增/更新的可摆放套件至少执行下列适用项，保存输入、实际结果与证据，不只写“通过”：

1. 0/90/180/270 度：图、锚点、安装孔、棕色轮廓、光学中心/方向一致；12.5 与 25 mm 板分别测试螺孔吸附。最少孔数量不足时必须报错。
2. 两件轮廓凹口可接近而不发生大矩形误报；真实接触要报错；底座越界报错、上部单独悬出允许；沉孔仅根据棕色轮廓遮挡。
3. 小板 4 孔失配拒绝；8 孔 4 个可用通过、3 个拒绝；桌面不要求根板孔对齐且导出不含根板；实体小板仍在清单。
4. 成组拖动/复制保持相对位置；副本改波片或出光参数不改原件；删一件移除其选配；撤销恢复几何和采购。工程导入失败不部分覆盖。
5. 有真实光学面者：从正确出光口出光，旋转后方向正确；空架只在已确认后直通；光高未知、光学基准未知或型号不支持应暂停而非伪造结果。
6. 已装光学片随复制、保存、共享和购物车；拆除后不再采购；更换镜型不沿用旧镀膜系数；多支路/往返距离与回退次数可区分。
7. 选择实测报告参数不重写无证据偏振角；导出俯视图包含当前可见光路；隐藏后不残留。
8. 材料/表面处理、原件与换柱数量、垫片支撑点乘数正确；清空画布车仍在；`removed:true,selected:true` 最终必须不导出；游客制造禁下载在服务端有效。

推荐复用源码已有 `test_*` 与 `qa/` 验证器，按变更范围运行，不把一次旧日志当新数据验收。交互模块依赖 `static/index.html` 的实际脚本加载顺序；多个文件扩展 `BreadboardEditor.prototype`，修改顺序可能覆盖前一个行为，不能随意重排。

## 12. 已知缺口 / 不可对外宣称的能力

以下是保留的能力边界；新增声明式语言见 [optical-language.md](optical-language.md)，不能以语言扩展推定旧器件缺少的数据已经补齐：

1. `PROJECT_FILES.md` 的类型表已补充 `dichroic/unsupported/internalOptics`；其他历史字段说明仍可能不完整，交接执行以本协议和当前解析器为准。`OPTICAL_RENDERING.md` 顶部版本较旧，正文有后续追加，不能只读头部。
2. 新类别若未写 `opticalType`，`elementType()` 最后回退为 `lens`。应显式配置类型；未知器件写 `unsupported`，不能默认赋焦距或当透明空气。
3. 未知安装孔的激光器当前可摆桌面，但不能通过有孔实体面包板的安装验收；399 nm 出光定位/高度仍待实测；1030 nm ECDL 与 1870 nm 光纤种子源仅资料缩略图，未定标不能拖放。这些状态须在逐件档案保留。
4. 当前镜厚核验记录是套件机械标定，不是每次更换采购镜片型号后自动重新移动光学面。使用不同厚度镜片时须再测后挡面与实际镜厚，更新基准/转接件；界面换型号本身只处理光学/采购数据。
5. 只有两级板、单个小板模块整组编辑；不是任意层级装配或多个板/散件混合组的完整 CAD 编辑器。
6. 二维碰撞、矩形底座与圆对称 Gaussian 模型都有范围限制；不能宣称完整三维干涉、任意镜片真实光场或任意多程目标偏振优化。
7. 当前 PBS 是理想器件；未知镀膜相位不会被恢复；厂家曲线之外不外推；双波片反求没有闭环多程求解。
8. 308 nm 垫板的孔组绝对位置仍按现有证据分级，且其自动生成专用，不能不加审核推广到别的激光器或异形板。
9. `layout.py::mounting_alignment` 对普通规则板的器件孔重合检查主要看孔阵坐标；不同于小板固定检查和注册板，它未在该函数内排除根板 `mountingHoles`。另有沉孔遮挡检查通常拦截相关情况，但导入者不能宣称这一条已是统一的 M6 螺纹配合验证，须列作后续一致性复核项。
10. 光学总装的一些材料/型号、镀膜面、厂家相位或光轴高度尚未完成确认。这些不应靠“整理协议”变成已验收；逐件清单保留待办和责任来源。

## 13. 机器可读交互索引的用法

配套 `library/generated/interaction-index.json` 逐项列出 52 个套件和 5 个登记板的当前交互映射。它是 **旁置派生索引**，不能作为运行时 catalog、项目文件或采购组成替代品。`interactionProfiles` 将交互能力标识连接到本文件章节；每记录含 `sourceRecordSha256`，整个索引绑定 `sourceCatalogSha256` 和生产 normalizer 文件哈希。

`freshInstanceConfig` 是实际调用 `Renderer.configFor(无实例optics、空采购选配、当前完整catalog)` 的结果，用于描述“新建时程序会如何初始化”，不能覆盖任何已保存实例。`effectiveRuntimeType` 同样只是代码执行结果；没有明确物理类型时 `contractPhysicalType=null`，并区分 `legacy-category-inference`、`legacy-port-inference`、`unknown-legacy-lens-fallback`。来源未核对的字段保留 null 或警告，不能因为 normalizer 返回了默认数字就标成测量完成。

可在源码根目录运行：

```sh
python3 tools/build-interaction-index.py --root . --node /实际/Node/可执行文件 --output /新索引路径/interaction-index.json
```

构建过程只读取 catalog 和纯 JS 模块，不创建浏览器 DOM、不启动服务器、不读写用户数据库。单条来源哈希算法为原 catalog 记录的 Python `json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)` UTF-8 字节的 SHA-256。若更换打包目录，可移动构建器但应将 `.py/.cjs` 保持同名同目录，并显式传 `--root`。整理资产/目录后重新生成索引并比较全部来源哈希，不能手工改能力布尔值冒充代码已支持。


## 固定横柱兼容字段（2026-10-05 候选补丁）

`layout.fixedUniversalPostComponentIds` 为可选、唯一字符串数组（最多 128 项）。每个 ID 必须同时位于本套件 `components` 和目录 `universalPostSeries.posts`。省略或空数组保持原行为；错误声明由 Python 目录验证和 JavaScript 高度逻辑拒绝。

固定柱保留原 ID、数量和完整 BOM，只从 Z 垫高/换柱候选中排除；实例 `universalPostSelection` 以固定柱为原柱时必须拒绝，不能静默忽略。该声明只适用于整个组件 ID 的所有同类柱均固定的套件，不能表达同一个 ID 内部分固定、部分竖直的数量拆分。

它不自动证明支撑刚度或任意整装垫高的紧固可行性。垫高整装仍使用原有独立支撑材料规则；支撑组数应按真实方案另定。多光高使用现有 `opticalAssembly`，标量 `opticalAxisHeightMm` 只作明确命名的输入端参考。`globalHeightComparable=false` 是现有高度函数自动派生的报告字段，不应伪造为目录开关。

部署本字段前必须同时采用 Python/JS 兼容补丁；旧版引擎会忽略未知字段，把横柱误认为竖直 Z 支撑。协议包不得在未部署兼容补丁的生产库中采用。


## 已核实三维总装的外部光高组（2026-10-06）

`layout.opticalAssembly.externalAxisHeightsMm` 可选，例如 `[135, 62.5]`。仅接受 `verified: true` 的总装；数组必须为 2–16 个有限、非负、不超过 10000 mm 的互异数值，每一项必须与总装某一真实光学面的 `nodes[].faces[].centerMm` 的 Z 坐标在 0.00001 mm 内一致。实例不能覆盖此声明；省略时保持原有全局等高检查。该字段与 `layout.opticalInteraction` 平面 DSL 无关，不赋予平面元件改变光高的能力。

这些高度相对套件安装基面。世界光高要加上小板厚度及小板垫高、实例垫高、已启用激光器垫板厚度和实际可实现的换柱高度差；根板自身厚度不加。不可实现的换柱不会产生可用高度组。

全局高度检查把每个声明组作为一组连通边，只在实际世界 Z 相等（容差 0.00001 mm）时连接不同组；所有普通器件的光高必须与最高普通器件的高度连通。例如有 135→62.5 mm 爬架时，135 和 62.5 mm 可共存；63.5 mm 仍不通过。与当前高度组不相连的另一只爬架不能放宽检查。此处只判断名义高度兼容，**不证明 XY 对准、入射方向、镜片已装或镀膜参数有效**；每根光线仍由三维真实光学面和原有参数门限独立检查。

默认自动垫高遇到已连通的正确高度，会保留其现有垫高；已正确接入的整块小板也保留原高度。需要校正时优先选择该连通组内最近、可用现有垫高/柱高精确达到的高度，避免自动创建脱离现有组的目标高度。明确输入目标高度仍按用户目标计算。未接入的三维总装继续要求手动设置并用真实光路检验。改变总装声明或其光学面高度后，前端高度缓存必须重新计算。
