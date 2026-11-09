# ZZLab 光学交互语言 v1

格式名 `zzlab-optical-interaction`，`version: 1`。本语言已接入当前二维光路引擎；新元件在 `kit.layout.opticalInteraction` 写入 JSON 后，手动继续、自动渲染、回退重放使用同一解释器。它是一套有限的声明语法，不接收 JavaScript、表达式、脚本、文件路径、远程 URL 或任意矩阵。

目标是把「什么光能进入 → 在这里执行什么物理作用 → 得到哪些输出」交给数据描述。几何来源、型号证据、采购及加工仍按元件导入协议登记；一段可执行 JSON 不是该元件真实参数的证明。

## 1. 一个完整元件如何接入

1. 先登记可信俯视尺寸、柱/安装锚点、实际光学平面与光口、安装孔、光高及原始证据。坐标字段继续使用现有 `layout.opticalCenterMm/opticalPortsMm/opticalAxisHeightMm/opticalDirectionDeg/opticalSurfaceAngleDeg`，碰撞与底座轮廓另行登记。
2. 设置明确 `layout.opticalType`。光源用 `source`；普通平面型可用 `mirror/pbs/waveplate/lens/coupler/empty/unsupported`。不要依赖未知类别自动被当成 `lens` 的旧兼容行为。
3. 在 `layout.opticalInteraction` 加入经本 Schema 验证的程序。平面元件用 `model: "planar"`；独立激光器用 `model: "source"`。v1 禁止同一元件同时绑定此程序和 `layout.opticalAssembly`。
4. 将实际安装的镜片、波片、焦距、有效口径及出光设置登记到原有 `opticalDefaults`、光学槽和实例属性。程序引用这些已有配置。`inserted/configured` 表示本实例是否已装及用户是否已确认；不要把自动默认值说成手册数据。
5. 运行 Python 校验、JS 共用 fixtures 与物理行为测试；重建交互索引；再用真实示例工程验证两面入射、反向双程、旋转、搬动小板、回退与购物车。

例：旋转波片后紧接理想 PBS 的等效薄元件：

```json
{
  "format": "zzlab-optical-interaction",
  "version": 1,
  "model": "planar",
  "heightToleranceMm": 0.1,
  "onNoMatch": "block",
  "inputs": [{
    "id": "horizontal",
    "direction": {"angleDeg": 0, "halfAngleDeg": 5, "bidirectional": true},
    "wavelengthNm": {"min": 532, "max": 532, "onMismatch": "block"},
    "steps": [
      {"op": "waveplate", "waveplates": [{
        "inserted": true, "fastAxisDeg": 22.5,
        "retardanceDeg": 180, "designWavelengthNm": 532
      }]},
      {"op": "pbs"}
    ]
  }]
}
```

这是教学参数；不得直接当作某个实物的标定。上面的作用都发生在同一个已登记光学平面，没有元件内部两片之间的厚度和传播距离。具有真实内部光路的复杂总装继续使用现有 `opticalAssembly` 三维平面引擎。

## 2. 输入端口条件与几何

所有长度为 **mm**，波长为 **nm**，功率为 **mW**，角度为 **度**。平面坐标 X 向右、Y 向上、逆时针为正；0° 为 +X、90° 为 +Y、-90° 为 -Y。图片像素向下不是物理 +Y。

| 条件 | 实际字段和执行含义 |
|---|---|
| 是否命中 | 先由 `planeHit` 和已登记光学平面找到交点，有限口径决定可命中的平面范围；DSL 不改变其位置，不在碰撞外框上任意创造光口 |
| 输入方向 | `inputs[].direction.angleDeg` 是**传播矢量**在该元件局部 XY 的方向，非「来光在哪一侧」；`halfAngleDeg` 为接受半角；实例及所属小板旋转后自动变换；`bidirectional:true` 同时允许反方向 |
| 输入规则选择 | 仅按方向匹配。必须恰好匹配一条规则；多条命中报 `interaction_ambiguous_input`。不同波段不能用重叠方向的多条规则来选择，v1 尚无波长分派 |
| 实际高度 | 输入束的 `beam.axisHeightMm` 与元件场景中的 `axisHeightMm` 比较，后者已包含板厚、垫高和换柱；两者都必须已知。差值不超过 `heightToleranceMm`；省略时继承会话容差（默认 0.1 mm） |
| 波长 | `wavelengthNm:{min,max,onMismatch}` 为闭区间；超出时显式 `block` 或 `warn`。省略是无该波段条件，不代表厂家保证全波段 |
| 口径 | `optics.clearApertureMm`。光轴虽命中但 `|offset| + 光斑半径 > 口径/2` 时报告截光警告，继续近轴传播；不伪造截光损耗或衍射 |
| 未匹配方向 | `onNoMatch:"block"` 暂停；明确 `"pass"` 才直通。若这个位置不是透射窗口，一般应选 block |
| 空架 | `inserted:false, configured:false` 需确认；明确 `inserted:false, configured:true` 直通，且仍需已知且匹配的高度。空架先于物理操作匹配，是用户明确移除光学片的语义 |

省略 `direction` 是方向通配；省略所有条件也不会绕过光高、实物基准、插片确认和口径检查。`opticalDatumVerified:false` 仍阻止计算。不能为了消除布局报错把未知高度写成 0、通用光高或扩大光高容差；容差是数值/装配接受条件，不是自动改变实际 Z。

`heightToleranceMm` 只控制高度匹配；v1 **不支持**把光线改成另一高度、上下折转或改变端口位置。新增三维功能须升级协议与解释器，不能通过额外字段偷偷表达。

## 3. 可执行作用与输出

每条规则允许 1–8 个步骤，按书写顺序施加到当前分支；PBS 可产生两个输出，后续步骤分别作用于它们。单次最多 16 个输出；还有整个会话的分支、步数和功率阈值限制。任一步失败会保留原待处理事件，不提交一半结果。

| op | 输入数据 | 输出定义与边界 |
|---|---|---|
| `pass` | 无额外参数 | 方向、高度、功率、偏振及 q 不变；自由传播的 q 更新由引擎处理 |
| `mirror` | 可选 `mirror`，省略时使用实例 `optics.mirror` 和已绑定的厂家数据 | 以当前 `elementAngle` 平面做镜面反射，按 Rp/Rs/相位差改变功率和偏振；q、高度不变。新 DSL 缺少镜面 mode 时阻断；只有主动选择的 ideal 才按明确警告的理想镜计算 |
| `pbs` | 使用实例平面角、PBS 手性及当前 Stokes | 理想 P 透射、S 反射；`P_T=P(1+s1)/2`、`P_R=P(1-s1)/2`，两束相应纯 P / 纯 S；q 与高度不变。当前尚无 PBS 消光比、透过率实测矩阵输入 |
| `waveplate` | 可选 `waveplates`，省略时引用已确认且包含完整参数的实例波片序列/单片配置 | 用现有 Stokes 延迟器变换，功率与 q 不变。显式数组中每片已插入波片必须在执行时具备快轴角、延迟角、设计波长；引用实例也必须有这些实际字段并已确认，不接受 normalizer 通用默认值。缺项会阻断，未装的片可仅写 `inserted:false` |
| `lens` | 可选 `focalLengthMm`，省略引用实例焦距 | 同一平面薄透镜：`q_out = 1/(1/q_in - 1/f)`，离轴中心线斜率按交点偏移/焦距改变。焦距未知阻断；大于 15° 倾角警告；掠入射阻断。功率、偏振、高度不变 |
| `coupler` | 可选 `halfAngleDeg`，默认 5° | 入射方向必须对着既有出光口进入（与出光矢量反向）；通过后终止为 `coupled`。理想接收，不声称实际耦合效率。出光仍由此实例 `optics.source.enabled` 控制 |
| `attenuate` | 必填强度透过率 `transmission` 0–1 | `P_out=P_in×T`；偏振、q、方向和高度保持。不支持增益或自行填写偏振相关透过矩阵 |
| `absorb` | 可选原因 `reason` | 分支终止为 `absorbed`，不会继续传播。终止记录保留到达吸收面的功率，不能把它误读成继续输出的功率 |
| `block` | 必填 `reason` | 拒绝执行并定位到此器件；适合已知位置但未知作用的占位元件 |

`mirror` 数据子对象沿用 `optics_settings.mirror / Engine.normalizeMirror`：`mode:"data"` 或 `"ideal"`，`samples` 数组，每点具备 `wavelengthNm/incidenceAngleDeg/reflectanceP/reflectanceS/phaseDifferenceDeg`。强度系数可明确为 `null`（未知），但不是零。真实数据模式只使用匹配的波长和 AOI，不猜测插值、外推、厂家下限或未给出的相位。

如果入射是纯 P、纯 S 或没有相关相干项、输出不依赖未知相位，允许使用已知强度系数并保留「相位未知但此次不影响输出」说明。一般椭圆/斜线偏振混合需要相位数据，否则阻断。理想镜的 `Rp=Rs=1, δ=180°` 是当前引擎的基底约定；不要再在实测总相位上叠加 180°。

可选步骤参数会覆盖实例的对应参数，**因此固定 inline 数据不会跟右键改实例参数而变化**。希望用户持续调节的波片、镜片及透镜，应使用 `{"op":"waveplate"}`、`{"op":"mirror"}`、`{"op":"lens"}` 引用实例设置。固定数据只用于证据明确的不可调作用。

## 4. 光源、耦合头与反向双程

独立激光器使用：

```json
{"format":"zzlab-optical-interaction","version":1,"model":"source",
 "emission":{"direction":{"angleDeg":0,"halfAngleDeg":0,"bidirectional":false},
             "wavelengthNm":{"min":532,"max":532,"onMismatch":"block"}}}
```

`emission` 是已有出光设置的限制，不提供默认激光报告参数，也不自动开启光源。出光口来自 `sourcePoint/opticalPortsMm/opticalCenterMm`，出光方向来自原有 `opticalDirectionDeg` 与实例角，波长/功率/光斑/偏振等来自已校验的 `optics.source`。未知真实出光高度必须阻断。source 模型没有 `inputs/onNoMatch`；planar 模型不得有 `emission`。

耦合头用 planar 的 `coupler` 接收步骤，同时可由既有 `source.enabled` 发光；v1 对这种双向耦合头没有单独 emission 条件块。接收方向条件若声明为 +90°，对应实际出光方向应为 -90°，例子仅说明这一约定。

同一器件可多次遇到，事件由实例、分支与经过次数区分，不能用「曾渲染过」跳过第二次作用。波片序列反向传播时按物理顺序倒序，并按现有偏振基底反转快轴角；不要自己预先再反转一次。一般多步骤程序仍按书写顺序执行，**不自动整体倒序**：只有一个 `waveplate` 步骤里的波片数组有已实现的逆向规则。需要反向不同操作时声明两个不重叠的单向输入规则；同一物理复合器件的反向传播须逐例验证。

## 5. 光束状态、精度和不能表达的事

| 状态 | 约定 |
|---|---|
| 功率 | `beam.powerMw` 是绝对功率；偏振使用归一化 Stokes，`s0=1`，偏振度 `sqrt(s1²+s2²+s3²) ≤ 1` |
| 偏振基底 | 沿用引擎 `exp(-iωt)`、右手 `(P,S,k)`、平面 `S=+Z`、`P=S×k`。一般斜线/椭圆偏振含相干交叉项；非偏振/非相干混合用 Stokes 表达 |
| Jones 与相干性 | 镜面物理作用等价使用复振幅系数，程序本身不接受任意 Jones 或 Mueller 矩阵。分支不保留统一绝对相位，没有跨路径干涉/相干合束；不能从单独两束功率推算干涉条纹 |
| q 参数 | `q={re,im}` 为 mm，`im>0`；自由传播 `q→q+d`。波长在物理函数内由 nm 换算为 mm。源光斑为 **1/e² 强度直径**；`wavefrontRadiusMm:null` 表示平面波前，不表示「尚未测量」的任意真实曲率 |
| 焦点和束腰 | 引擎从 q 推出当前半径、波前曲率、焦点位置；透镜改变 q 后焦点/直径自动更新。`M²>1` 使用有效二阶矩近似，不能当作严格相干 TEM00 波前 |
| 路程 | 显示实际几何线段长度累积，不是折射率加权的光程；薄元件步骤自身无厚度和内部距离 |
| 颜色 | 根据波长映射显示，紫外/红外为示意色；不是肉眼真实颜色。线宽按相对功率温和缩放，光束包络按 q 的实际光斑 |

v1 不支持任意输出端口 XYZ、主动改高度、3D折转、厚透镜/基片折射、色散模型、增益、衍射、散射、有限孔径衍射、非线性频率转换、全电磁场或跨束相干叠加。未知条件不要用自创字段表示；校验器会拒绝。物镜总装用 `layout.opticalAssembly` 的既有内部三维面和独立侧视渲染，机械物镜入口按真实已核实面终止，不伪造样品焦点。

## 6. warning、block、pass 及持久化

- **block**：缺数据、未知光高、方向不匹配、模糊规则、非物理输出、未知操作等。保留待处理事件、定位器件；一键渲染列出问题，手动也不能绕过。
- **warn**：明确允许的波段超出、波片设计波长不符、口径可能截光、理想镜/耦合近似、近轴限制。光继续，但必须保持精度说明；不会偷偷补厂家数据。
- **pass**：有意直通，包括已确认空架、`pass` 步骤和显式 `onNoMatch:"pass"`。它不是缺信息时的通用错误恢复。

程序属于可信 catalog 元件类型，**不放在工程实例里**；实例保存用户可调光学配置、插片和选购物料。复制实例会复制已有实例设置；项目导出引用 kit ID，并保存实例参数和是否重新计算/显示光路的偏好；不保存陈旧追迹坐标或逐次事件。换程序或几何会改变 trace key 与 renderer optical signature，旧事件不能盲重放；渲染重新验证后更新。程序不新增采购行，采购仍由元件 BOM 和已装光学槽产生，不能因一个 `mirror` 操作凭空多买一块镜片。

当前没有网页 DSL 编辑器；其他 AI 通过元件库文件导入、检查、发布。新增 op 需要版本、前后端校验、引擎、Schema、示例和测试一起改，不允许只放行后端字段。

## 7. 文件与验收

- Schema：项目 `library/schemas/optical-interaction.schema.json`（JSON Schema 2020-12）。JSON Schema 仅能表达结构/数值范围，互斥方向、min≤max、重复 ID、重复镜面波长/AOI、物理数据充分性和能量守恒由前后端验证器及引擎执行。
- 示例：项目 `library/examples/optical-interaction/*.json`，覆盖镜、PBS、波片、透镜、耦合头、激光、空架、未知与双程组合。标有 inherit 的例子需要先填实例参数；mirror-data 引用实例真实数据，不能只凭该模板保证已有镀膜相位。
- 解释器：`static/optical-interaction-language.js`；接入：`static/optical-engine.js::normalizeInteractionElement/interactionResult/advanceInteraction/createSession/pendingIssue`、`static/optical-renderer.js::sceneFor/continueOpticalAt/opticalSignature`。
- 后端：`optical_interaction.py::validate_optical_interaction`；公共结构用同一 `tests/fixtures/optical_interaction_validation.json`；行为测试 `tests/test_optical_interaction_language.cjs`。
- 加载顺序：`optical-interaction-language.js` 在 `optical-engine.js` 之前，renderer 在 engine 之后。Node 使用延迟 require；没有注入任意依赖代码的字段。
- 派生索引：`library/generated/interaction-index.json` 和 `port-index.json`，由 `tools/build-interaction-index.py` 根据实际 normalizer 生成。每项保留原 record SHA，索引保留 catalog SHA 与解释器/验证器/构建器 SHA。

当前已有元件的旁置端口索引标为 `legacy-derived`；这只是逐件记录现有行为，没有把 52 个旧元件自动改成新 DSL。`declared` 仅用于 catalog 实际含 opticalInteraction 的项；`unknown-legacy-lens-fallback` 永远保留 unknown，不冒充确认的透镜。5 个注册面包板是机械载体/模块边界，不是自动的透射光学平面。

属性面板会标明「由交互协议定义」并显示输入规则与步骤；类型固定，不能用下拉框改成另一套作用。写死在程序里的镜面、波片或焦距不显示误导性的对应实例编辑框；引用实例的参数继续可调，插片与采购仍可修改。

## 用一个隔离 JSON scene 做前向试算

从项目根目录执行（node 可替换为本机 Node 可执行文件）：

```sh
node tools/trace-optical-scene.cjs library/examples/scenes/attenuator-lens.scene.json
```

命令只读取 JSON 和现有引擎，输出 JSON 到标准输出，不写元件库、catalog、账号数据库或文件，不访问网络。退出码 0 表示完整计算，1 表示阻断或预算内未完成，2 表示输入无效。输出包含 issues、每段起终点的功率/Stokes/q/光斑、实际束腰位置和终止原因；吸收/耦合等终止记录若未暴露作用后 Stokes/q，会明确返回 finalBeam:null，不能拿作用前状态冒充作用后状态。

示例是纯合成教学场景，不是实物标定。一个已知 62.5 mm 光高的 532 nm、10 mW、2 mm 光斑椭圆偏振源，经过 100 mm 自由传播，进入同一平面上依次执行 attenuate(0.8) 和 lens(50 mm) 的双向器件。输出应为 8 mW，归一化 Stokes 不变，束腰在薄透镜之后约 50.0036 mm。两个步骤共面；没有假设器件内部传播距离或折射率。

scene 的顶层是 bounds/elements/可选 modules。每个 element 的 center 是已转换的场景光学平面坐标，axisHeightMm 是最终光高，optics 包含已确认光学配置。直接试算时把程序放到这个隔离场景 element.opticalInteraction；正式元件库仍写 kit.layout.opticalInteraction。这个场景结构不是工程 .zzoptics.json，也不是 package.json；不要把试算场景的程序直接塞入用户工程实例或以教学光高替代未知实物参数。

CLI 固定使用 pauseOnHeightErrors:true，并设置步数、线段数、分支数、路程、总事件数和执行时间上限。未知光高、缺有效参数、规则歧义或不允许的方向/波长都会给出可定位的问题，不会通过放宽几何条件继续算。无有效开启光源也是阻断，不能将没有产生任何光线认作通过。

若直接使用 Node API，现有入口为：

```js
const E = require('./static/optical-engine.js');
let s = E.createSession(scene, undefined, { pauseOnHeightErrors: true });
let batch = E.autoAdvance(s, { maxEvents: 128, maxMilliseconds: 50 });
// batch.canContinue 时可继续下一批；真实自动化应同时设置总体事件/时间预算。
```

参数完整性由声明与实际配置共同决定；仅 Schema 验证通过不代表物理参数完整。反向整体步骤不会自动倒序；同方向多波段分派目前不支持，重叠方向规则会明确阻断。
