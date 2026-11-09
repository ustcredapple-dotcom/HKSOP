<p align="center">
  <img src="docs/assets/hksop-cover.svg" alt="HKSOP — Hong Kong Standard Optical Protocol. A unified component library and layout tool for modular tabletop optics." width="100%">
</p>

<h1 align="center">HKSOP · 模块化实验光路设计与管理工具</h1>

<p align="center">A practical toolset for designing, checking, and building tabletop optical setups.</p>

<p align="center">
  <a href="#overview">项目介绍 Overview</a> ·
  <a href="#design">设计思路 How It Works</a> ·
  <a href="#layout">目录说明 Repository Tour</a> ·
  <a href="#quick-start">快速上手 Quick Start</a> ·
  <a href="#workflows">使用方法 Workflows</a> ·
  <a href="#examples">示例光路 Examples</a> ·
  <a href="#documentation">相关文档 Docs</a>
</p>

<p align="center">
  <a href="https://www.ultracold.hku.hk/">HKU Ultracold Atom Lab · ZZLab</a> ·
  <a href="mailto:u3013215@connect.hku.hk">Wang Junjie</a>
</p>

<a id="overview"></a>
## 项目介绍 / What is HKSOP?

在实验室搭一套模块化光路，从头到尾要处理不少零散的工作：挑镜架和光学元件，在面包板上排好位置，计算光路，再去三维软件里拼总装、检查干涉，最后列采购清单、准备转接件的加工资料。如果这些步骤各用各的文件，换一个镜架或者调整一下光轴高度，二维图、三维模型和采购单就得挨个手改，很容易漏掉。

**HKSOP（Hong Kong Standard Optical Protocol）的设计来自香港大学 HKU Ultracold Atom Lab（ZZLab）**。我们把常用元件的厂家型号、安装孔位、真实光学面的坐标、二维俯视图和三维 STEP 模型，组织成统一格式的元件包。网页编辑器、光路计算、三维装配复建和 BOM 导出使用同一套定义：二维布局确定后，可以按元件已支持的交互规则检查光线与高斯光束传播，再用配套脚本复建三维子装配和总装，整理采购需求。

这个私有仓库是我们自用的精选版本。当前有 **694 个元件包**，包含 **432 条零件记录、263 条装配套件记录和 6 种底板定义**，配套 **584 份去重 STEP、376 份俯视资源、539 份 PDF 和 349 份 DXF**，以及基础反射、一分三和 DoublePass 三个工程 JSON 示例。一个包可以包含多条记录，包数与记录数不是同一个统计口径。当前资料版本为 `2026-11-09.hksop-github-cad-2`。

元件对应的现用三视图、加工图和激光打标资料也随库提供，按内容哈希去重，沿用原记录中的修订和验收状态。具体文件及覆盖范围可查[收录范围](docs/selection.json)、[资源清单](docs/asset-manifest.json)和[图纸恢复记录](docs/cad-restoration.json)。具体项目的历史三维成果和整套交付压缩包不在这个精选版本中。

Building a tabletop optical setup usually involves several separate files: part lists, a breadboard layout, ray-tracing inputs, a CAD assembly, purchasing spreadsheets, and drawings for custom adapters. Changing one mount or the optical axis height can mean updating all of them by hand.

**HKSOP was developed at the HKU Ultracold Atom Lab (ZZLab), The University of Hong Kong.** It brings part numbers, mounting hole coordinates, optical reference surfaces, top-view assets, and STEP models into a common component package format. The web editor, optical calculations, 3D assembly rebuild, and BOM export use these definitions. After arranging a layout, you can check ray paths and Gaussian beam propagation for supported elements, reconstruct sub-assemblies and the full assembly with the CAD workflow, and prepare the purchasing BOM.

This private, curated edition contains the package and asset counts listed above, including current component drawings and laser-marking files. Package counts and record counts measure different things: one package may contain several records. Asset revisions and existing verification states are preserved. See the [scope](docs/selection.json), [asset manifest](docs/asset-manifest.json), and [drawing restoration record](docs/cad-restoration.json) for the exact contents; historical project assemblies and complete delivery archives are outside this edition.

<a id="design"></a>
## 设计思路 / How It Works

首先，图片对齐不能代替孔位和光学基准的核对。二维俯视图用于显示，STEP 提供三维几何；元件装在哪个安装孔上、实际反射或透射面在什么位置、光线如何与元件作用，都需要在协议中明确。这样才能把屏幕上的布局与实际装配联系起来。装配公差、调整范围和实物表现仍需按具体设计检查。

每个元件在 `library/` 下有自己的包目录，维护记录、资源和必要说明。正式启用的包登记在 `library/registry.json`，由编译器汇总为 `catalog.json` 和检索索引。修改旧元件或添加新元件时，主要维护对应的包；未登记的草稿不会进入当前支持清单。

同一型号换成 45°、90° 或另一种转接装法时，可以共用确实相同的采购零件记录，但安装接口、孔位、支撑高度和光路参数要分别描述。转接件或紧固件发生变化时，BOM 也要跟着更新，不能只旋转二维图片。

项目文件 `project.zzoptics.json` 记录选用的套件、位置、方向、板层、光源和光学设置等工程数据，模型与图纸留在元件库中。较大的资源集中存放在 `library/assets/sha256/`，按内容哈希去重。多个项目引用同一个元件时，共用同一份资源。

元件资料做到哪一步，就记录到哪一步。每个包分别声明 `display`、`placement`、`simulation`、`procurement` 和 `manufacturing` 的状态与证据。只有采购型号和外形资料的元件，可以先用于相应工作；尚未核验的光学参数或制造信息保持待核验，不填假定值来凑齐状态。

Visual alignment is only a starting point. Top-view assets provide the display, STEP files provide 3D geometry, and the protocol defines mounting holes, optical reference surfaces, and beam interactions. These definitions connect the screen layout to the assembly; tolerances, adjustment ranges, and physical performance still need to be checked for the actual design.

Each component package is maintained independently under `library/`. Packages listed in `library/registry.json` are compiled into the shared catalog and indexes, while unregistered drafts stay outside the supported inventory. Mounting variants reuse genuinely shared part records and define their own interfaces, support geometry, optical behavior, and any changed BOM items.

Project JSON files store the layout and optical settings rather than duplicating models and drawings. Assets are shared by content hash under `library/assets/sha256/`. Readiness is tracked separately for display, placement, simulation, procurement, and manufacturing, with evidence for each; an unverified property remains unverified.

<a id="layout"></a>
## 目录说明 / Repository Tour

仓库把软件、元件和具体工程分开维护。`engine/` 负责校验、摆放、光路计算、渲染、CAD 辅助和界面；`library/` 保存当前元件定义及资源；`projects/` 放示例工程；`skills/` 和 `docs/` 提供操作规范与说明。各主要目录的说明提供英文入口。

The repository separates software, component definitions, and project layouts. `engine/` contains validation, layout, optics, rendering, CAD helpers, and applications; `library/` holds the current definitions and assets; `projects/` contains example layouts; and `skills/` and `docs/` contain workflows and documentation. Directory guides include English versions.

```text
HKSOP/
├── hksop.py                         # 命令行入口 / Main CLI
├── engine/                          # 校验、布局、光学与 CAD / Software engine
├── library/                         # 当前元件库 / Current component library
│   ├── standard/                    # 标准装配套件 / Standard kits
│   ├── components/                  # 采购件与自制件 / Purchased and machined parts
│   ├── modules/                     # 组合模块 / Composite modules
│   ├── boards/                      # 底板与孔位 / Boards and hole patterns
│   ├── custom/                      # 项目定制定义 / Project-specific definitions
│   ├── assets/sha256/               # 模型、俯视图与图纸 / Models, views and drawings
│   ├── registry.json               # 已登记的包 / Registered source packages
│   └── catalog.json                # 自动生成的总表 / Generated catalog
├── projects/                        # 示例光路 / Example layouts
├── skills/                          # 设计、入库与交付规范 / Engineering workflows
├── docs/                            # 说明与验证记录 / Documentation and verification
└── config/                          # 范围及本机配置 / Scope and local configuration
```

库里的 `components` 是单独采购或加工的零件，例如镜架、接杆和转接件；`kits` 是由这些零件组成、可以在编辑器里摆放的装配单元；`registeredBoards` 描述底板的真实外形、孔位和修订。项目中的实例则记录某个套件在这次工程里的位置、方向和设置。

平时修改元件，以各包的记录文件和 `registry.json` 为源。`catalog.json`、各类索引、HTML 目录和 `runtime/` 是构建结果，改完源文件后重新生成即可。`library/snapshots/web-current` 是当前兼容索引，不是历史元件库备份。

In the library, `components` are individual purchased or machined parts, `kits` are placeable assemblies, and `registeredBoards` define board geometry, mounting holes, and revisions. Project instances describe where a kit is used and how it is configured in a particular layout. Edit the package records and registry, then rebuild the generated catalog, indexes, and runtime. `library/snapshots/web-current` is the current compatibility index, not a historical library archive.

<a id="quick-start"></a>
## 快速上手 / Quick Start

仓库使用相对符号链接共享资源，以下步骤适用于 macOS 或 Linux，克隆时需要保留这些链接。准备好 Git 和 Python 3，并配置有权访问这个私有仓库的 GitHub SSH 账号。命令行光学追迹另外需要 Node.js。

The repository uses relative symlinks for shared assets. The commands below target macOS or Linux with symlink support, Git, Python 3, and SSH access to this private repository. Node.js is also needed for CLI optical tracing.

**下载并安装依赖 / Clone and install**

```bash
git clone git@github.com:ustcredapple-dotcom/HKSOP.git
cd HKSOP

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r engine/requirements-runtime.txt
```

**生成总表并启动编辑器 / Build and launch**

```bash
python hksop.py catalog check
python hksop.py catalog build
python hksop.py runtime build --profile editor
python hksop.py serve --profile editor --port 18945
```

启动后，用浏览器打开 **[http://localhost:18945](http://localhost:18945)**，导入 `projects/` 下示例目录中的 `project.zzoptics.json`。第一次可以先用基础反射示例熟悉导入、拖动和旋转，再看一分三与 DoublePass 的组合布局。

Open **[http://localhost:18945](http://localhost:18945)** and import a `project.zzoptics.json` from `projects/`. Start with Basic Reflection to try importing and manipulating a kit, then explore the larger 1-to-3 and DoublePass layouts.

<details>
<summary><strong>可选：三维 CAD 环境与本机路径 / Optional: CAD environment and local paths</strong></summary>

三维 CAD 功能另外使用 [CAD 依赖](engine/requirements-cad.txt)。可以在独立 Python 环境中安装，再将[配置模板](config/local-environment.example.json)复制为 `config/local-environment.json`，把解释器路径填入 `cadPython`。同一配置也可以指定运行时 Python 和 Node.js；未配置时，使用当前 Python，命令行追迹从 `PATH` 查找 Node.js。本机配置不提交到 Git。

CAD operations require the [CAD dependencies](engine/requirements-cad.txt). Install them in a separate Python environment if needed, copy the [configuration template](config/local-environment.example.json) to `config/local-environment.json`, and set `cadPython` to that interpreter. You can also specify the runtime Python and Node.js paths. Defaults use the current Python and Node.js from `PATH`; the local configuration is ignored by Git.

</details>

<a id="workflows"></a>
## 使用方法 / Everyday Workflows

### 添加新元件 / Adding a component

买了新器件或完成新的转接件设计后，可以从 [元件包模板](engine/templates/component-package/)起步，或参考最接近的现有套件。为新包和记录分配唯一、稳定的英文 ID，填写型号、来源、BOM，以及实际已有的机械和光学数据。采购零件不必虚构套件几何；需要在编辑器中摆放的套件，则要说明安装孔位、光学基准和交互规则。

把当前模型、俯视图和适用图纸登记到包中，写明相对路径、运行目标路径与 SHA256，并分别记录五项能力的状态和证据。随后运行下面三条命令。通用标准包将第二条命令中的 `custom` 改为 `standard`，第三条中的 `<stage-id>` 使用上一步返回的实际名称；暂存期间库有变化时，要重新执行 stage。

Start from the [package template](engine/templates/component-package/README.en.md) or a similar kit, assign stable English IDs, and describe the part numbers, sources, BOM, and available engineering data. A purchasing record does not need invented geometry; a placeable kit needs mounting geometry, optical datums, and interaction rules. Register the current assets with relative paths, runtime targets, and SHA256 hashes, then record the five readiness states with evidence. Use `standard` instead of `custom` for standard packages, replace `<stage-id>` with the returned value, and stage again if the library changes before adoption.

```bash
python hksop.py package check /path/to/new-package
python hksop.py package stage /path/to/new-package --collection custom
python hksop.py package adopt runtime/staging/<stage-id>
```

合入后重建 catalog 和 runtime，在实际项目里检查俯视图、安装孔、光轴高度、追迹与 BOM，并记录结果。包检查和暂存检查可以发现结构、全库契约、BOM 或声明资产的问题，不能替代几何核验与实物装配。详细步骤见[元件入库指南](docs/component-intake.md)和[上传规范](skills/hksop-component-upload/SKILL.md)。

After adoption, rebuild the catalog and runtime and verify the package in a project. Check the top view, mounting holes, optical axis height, supported tracing, and BOM output. Package checks cover structure, catalog contracts, BOM references, and declared assets; they do not certify physical fit. See the [onboarding guide](docs/component-intake.en.md) and [upload workflow guide](skills/hksop-component-upload/README.en.md).

### 搭光路、复建三维与准备交付 / Designing and delivering a setup

先确定底板、光轴高度和所需套件，再在编辑器中摆放器件、配置入射光，检查孔位、干涉和光路，保存当前 `project.zzoptics.json`。三维复建流程使用配套 STEP 和布局变换建立器件子装配及总装，随后还要核对层级、内部姿态和装配基准。

采购时从 BOM 整理型号、数量和来源。需要加工自制件或交付整套系统时，按[加工包规范](skills/hksop-manufacturing-package/SKILL.md)或[客户包规范](skills/hksop-customer-package/SKILL.md)，检查当前修订的模型、工程图、孔与螺纹标注、材料、表面处理和打标要求。**STEP 可以是装配模型或加工几何，但单独一份 STEP 不等于完整加工包；下单前需要核对相应图纸、工艺要求和验收状态。**

Choose the board, optical axis height, and kits, then place the components, configure the beams, check mounting constraints and clearances, and save the project JSON. The 3D workflow rebuilds kit sub-assemblies and the overall assembly from the library STEP files and layout transforms; verify the resulting hierarchy, internal poses, and datums.

Use the BOM to prepare purchasing quantities and sources. For custom machining or system handoff, follow the [manufacturing](skills/hksop-manufacturing-package/README.en.md) or [customer delivery](skills/hksop-customer-package/README.en.md) guide and check the matching model revision, drawings, hole and thread callouts, material, finish, and marking requirements. A STEP file can provide assembly or machining geometry, but it is not a complete manufacturing package by itself.

<a id="examples"></a>
## 示例光路 / Example Setups

[基础反射示例](projects/基础反射示例/project.zzoptics.json)含一个可调反射镜架实例，用来熟悉工程结构和编辑器操作；它没有配置光源，是最小摆放示例。[一分三示例](projects/一分三示例/project.zzoptics.json)含 18 个实例，展示分支光路中多个标准套件的组合。[DoublePass 示例](projects/DoublePass示例/project.zzoptics.json)含 12 个实例，展示往返光路和项目定制套件的使用。

三个工程均有当前编辑器的兼容性检查记录，详见[示例验证](docs/example-verification.json)。各项目目录保留来源和适配说明，原有的物理与制造验收范围不因作为示例而改变。

[Basic Reflection](projects/基础反射示例/README.en.md) contains one adjustable mirror-mount instance for learning the project format and editor controls; it has no configured light source. [1-to-3](projects/一分三示例/README.en.md) uses 18 instances to demonstrate a branching layout. [DoublePass](projects/DoublePass示例/README.en.md) uses 12 instances, including project-specific custom definitions. All three have editor compatibility check records; their original physical and manufacturing acceptance limits remain unchanged.

## 文件管理约定 / File and Version Rules

引擎和元件库只维护当前有效的代码、定义及现用资源，不同现用型号和安装变体可以并存。当前元件的 STEP、俯视图和配套图纸属于正式库资源；项目按需要保留当前最终成果，历史只保留人工确认或正式交付的工程 JSON 里程碑，并按内容去重。

这个仓库只放三个当前示例，不附历史项目的三维总装、旧 CAD、旧图纸或旧交付包。`runtime/`、构建缓存、项目日志和 `config/local-environment.json` 留在本机。历史 JSON 再打开时，需要检查它与当前元件库是否兼容。完整规则见[保留策略](docs/retention-policy.md)。

The engine and library retain active code, definitions, and assets, including current component models and drawings. Active mounting variants can coexist. Projects retain their current deliverables as needed; historical retention is limited to deduplicated, confirmed engineering JSON milestones. This repository includes three current examples, without historical project CAD or delivery packages. Runtime data, build caches, local logs, and machine configuration are not committed. Historical JSON files must be checked against the current library when reopened; see the [retention policy](docs/retention-policy.en.md).

<a id="documentation"></a>
## 相关文档 / Documentation

了解文件关系可先看[架构说明](docs/architecture.md)和[元件库说明](library/README.md)，命令用法见[命令参考](docs/commands.md)。设计新元件时，结合[设计规范](skills/hksop-component-design/SKILL.md)、[入库指南](docs/component-intake.md)与[包结构 schema](engine/schemas/hksop-package.schema.json)。让助手参与工作前，先读 [HKSOP 上下文](skills/HKSOP_CONTEXT.md)，再选择[标准光学协议](skills/hksop-standard-optics/SKILL.md)及对应专项规范。

需要核对资料时，可查看[收录范围](docs/selection.json)、[资源清单](docs/asset-manifest.json)、[初始本地验收](docs/verification.md)、[运行验证](docs/runtime-verification.json)和[示例验证](docs/example-verification.json)。初始记录描述的是当时状态；当前清单应从 `main` 上的元件包重新编译，生成的 `catalog.json` 本身不提交到 Git。

English readers can start with the [architecture guide](docs/architecture.en.md), [library guide](library/README.en.md), [CLI reference](docs/commands.en.md), and [component onboarding guide](docs/component-intake.en.md). The [skills directory guide](skills/README.en.md) explains the design and delivery workflows, and the [documentation index](docs/README.en.md) links to English guides and verification records. Build the current catalog from the source packages on `main`; the generated `catalog.json` is not tracked in Git.

## 来源与联系 / Origin and Contact

本项目的设计来自**香港大学 HKU Ultracold Atom Lab（ZZLab）**。实验室网页为 [Ultracold@HKU](https://www.ultracold.hku.hk/)。项目联系 **Wang Junjie**，邮箱 [u3013215@connect.hku.hk](mailto:u3013215@connect.hku.hk)，GitHub 为 [ustcredapple-dotcom](https://github.com/ustcredapple-dotcom)。

This design comes from the **HKU Ultracold Atom Lab (ZZLab), The University of Hong Kong**. Visit [Ultracold@HKU](https://www.ultracold.hku.hk/) for the lab website. For this project, contact **Wang Junjie** at [u3013215@connect.hku.hk](mailto:u3013215@connect.hku.hk) or through [ustcredapple-dotcom](https://github.com/ustcredapple-dotcom).

---

<p align="center"><strong>HKSOP · Hong Kong Standard Optical Protocol</strong><br>HKU Ultracold Atom Lab · ZZLab</p>
