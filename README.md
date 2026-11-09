# HKSOP-github

ZZLab 标准光学协议精选版本，仓库采用私有可见性。元件版本 `2026-11-09.hksop-github-local-1`。

包含当前标准套件、共用采购件及它们实际依赖的自制零件，以及一分三和 DoublePass 使用的定制定义。统一支持清单由 `library/registry.json` 编译生成。

```text
HKSOP-github/
├── hksop.py
├── engine/       # JSON编译、摆放、光学追迹、渲染、CAD与导出
├── library/      # 当前元件定义、STEP、俯视渲染及统一清单
├── projects/     # 基础反射、一分三、DoublePass三个工程JSON示例
├── skills/       # 元件设计、入库、加工与客户交付流程
├── docs/         # 范围、操作、资产清单与验证
└── config/       # 当前副本范围与可移植配置
```

## 当前内容

- 432 个采购/制造零件、263 个套件、6 种当前所需板型，共 694 个独立元件包。
- STEP按内容去重保存；俯视渲染图用于编辑器显示。此副本不包含三视图、PDF/DXF加工图、打标图纸、整套项目交付包和项目历史。
- 三个示例仅保留工程JSON。一分三示例将旧选配字段 `diameterMm` 和额外元数据保存在说明文字中，并将时间格式适配为毫秒精度，保持器件布局与光路参数；原值及具体改动见示例的 `example.json`。
- 图纸未随此副本提供，不能据此声称加工包完整或制造放行。元件原有物理验证范围仍以记录为准。

完整包清单和筛选范围见 [selection.json](docs/selection.json)，STEP与渲染文件哈希见 [asset-manifest.json](docs/asset-manifest.json)。

## 使用

```sh
python3 hksop.py catalog check
python3 hksop.py catalog build
python3 hksop.py runtime build --profile editor
python3 hksop.py serve --profile editor --port 18945
```

打开 `http://127.0.0.1:18945/`，导入 `projects/` 下的 `project.zzoptics.json`。运行依赖见 `engine/requirements-runtime.txt`；CAD生成依赖见 `engine/requirements-cad.txt`。`config/local-environment.json` 是本机可选解释器配置，不纳入后续Git提交；其他机器可参考同目录的 example 文件。

编辑独立元件包后重建清单；不要直接修改生成的 catalog 或 runtime。入库见 [component-intake.md](docs/component-intake.md)，保留规则见 [retention-policy.md](docs/retention-policy.md)。

## GitHub状态

私有仓库：[ustcredapple-dotcom/HKSOP](https://github.com/ustcredapple-dotcom/HKSOP)。STEP模型直接纳入Git并按内容去重，不需要Git LFS。

```sh
git clone git@github.com:ustcredapple-dotcom/HKSOP.git
cd HKSOP
```

本机解释器配置、日志及生成的runtime不提交。`docs/verification.*`记录初始内容验收；发布状态以远端分支和本地PROJECT_LOG.md为准。
