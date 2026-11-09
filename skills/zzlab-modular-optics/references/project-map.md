# 当前工程入口（2026-10-05快照）

这些是定位既有工程的入口，不是要求未来沿用同一天的版本。开始任务时核实文件存在、最新修订和责任范围；路径失效时先按文件名/编号在当前工作区和NAS查找，不能自动回退到旧尺寸。

## 根目录与Onshape

- 本地工程根：`/Users/wjj/Documents/Codex/2026-10-03/onshape`
- NAS根：`/Volumes/ZZLab_001/Wang Junjie/模块化光路`
- 下表路径除特别注明外，均相对本地工程根。`work`是工作源与核验，`outputs`是已交付快照；打包内部也保留源，不能只保存不可复建的STEP。
- 当前器件文档：[光路模块化补充器件](https://cad.onshape.com/documents/fd8b55510f12b0bdce032326/w/d67de20d807c6dd6e1db6440)
- 正式公制柱来源版本：[公制万能柱](https://cad.onshape.com/documents/3a3c1d8089df865b8b4e822a/v/717979e25918fc346b4f0518/e/c0b5b3ef527f26d35662c923)。另一负责人维护；当前任务未要求改柱时仅引用。
- 爬架R2冻结版本：[一体爬架H200→50总装](https://cad.onshape.com/documents/fd8b55510f12b0bdce032326/v/03ced9e4c9cb5411260e33dd/e/a1287583dcdb144650c976ee)

Onshape当前类别沿用 `01_当前设计_公制M1_光高62p5`。爬架在其下 `06_爬架与高度转换/25_一体式爬架_R2_45宽_50与62p5`，内分定制件、50输出总装、62.5输出总装、工程图、装配引用。源STEP置 `90_STEP导入源`，旧版放历史。其他器件按实际树复用类别，不照搬爬架目录或盲建重复文件夹。

## 全系列当前源

| 入口 | 用途 |
|---|---|
| `work/metric_20261005/adapter_manifest.json` | 28种自绘件的当前STEP、源哈希、改版方式、孔/刻字证据。顶层“等柱”文字是中途状态，不代表最终总装仍未完成。 |
| `work/metric_20261005/migration_plan.json` | 63.5→62.5各件高度分配及例外；作为历史变更依据，不是当前完成回执。 |
| `work/metric_20261005/assembly_integration/assembly_manifest.json` | 正式公制柱集成后的总装清单；此批34套。 |
| `work/metric_20261005/assembly_integration/formal_posts/manifest.json` | 所需12.5/25/37.5/50正式柱的来源、坐标变换、接口、哈希；含对方源目录。 |
| `work/metric_20261005/assembly_integration/post_interface_reviews.json` | 柱与转接件的孔族、clock及紧固核验。 |
| `work/metric_20261005/post_fastener_length_table.json` | 按实际厚度/正式柱重算的螺长与旋入条件。 |
| `work/metric_20261005/supplier_fit_review.json` | 商用配合与已知限制，避免只按外形说能装。 |
| `work/metric_migration_20261005/drawing_manifest.json` | 最终公制加工图与源哈希；图纸spec在同目录`specs`内。 |
| `work/metric_20261005/onshape_metric_final_receipt.json` | 最终云端CAD/工程图/版本记录；确认元素与版本用此回执再实查。 |
| `work/metric_20261005/package_receipt.json`、`nas_receipt.json` | 本地/云端/NAS打包最终状态与哈希。 |
| `outputs/公制光路模块_62.5mm_M1_2026-10-05` | 本批完整交付；各器件`装配与检查说明.txt`含装配顺序、例外和未知基准。NAS同名目录为副本。 |

镜面审计位于 `work/metric_20261005/mirror_reference_audit/`，优先读取 `mirror_datum_review.json`、`source_seat_review.json`、`official_spec_crosscheck.json`。现有17号后座+12 mm落在柱中心；18号实际偏0.4 mm按用户宽限保留。该结果不能移植给别的镜架或镜片厚度。

源脚本入口：`work/metric_20261005/build_metric_adapters.py`；公制总装生成在 `work/metric_20261005/assembly_integration/` 下的 `prepare_jobs.py`、`integrate_assembly.py`、`run_batch.py`。它们有固定输入/输出和历史版本依赖，先读代码、复制为新修订再运行，避免覆盖正式件。

## 爬架R2

以 `work/periscope_r2_20261005/` 为当前源。`work/periscope_20261005/` 是R1及前期装配源，不能作为当前一体L几何。

| R2相对路径 | 用途 |
|---|---|
| `build_monolithic_bracket.py`、`engrave_linear.py` | 单实体L件及已修复刻字的生成器。 |
| `models/25-L1_R2.step`、`specs/25-L1.json` | 冻结加工单件及参数。 |
| `build_assemblies_r2.py`、`assembly_manifest.json` | 18套高度总装及源引用；不可只改单件而保留旧装配。 |
| `geometry_independent_review.json`、`glyph_repair_review.json` | 结构/孔/刻字独审；修复字形时未改功能面。 |
| `all18_height_and_axes.json`、`endpoint_H100_O50.json`等 | 全高度轻量检查与端点干涉/工具检查，声明实际检查范围。 |
| `make_drawing_spec.py`、`draw_assembly.py`、`drawing_manifest.json` | 加工3页+装配3页的输入与冻结回执。 |
| `cloud_roundtrip/summary.json`、`cloud_reference_warning.json` | 新L云端往返通过；商用镜架参考叶子警告仍被保留。 |
| `cloud_delivery/cloud_receipt.json`、`package_notes/package_receipt.json` | R2云端版本及完整资料包最终交付，不用早期bracket_manifest状态替代。 |

完整交付目录：`outputs/25_公制一体L型爬架_100-200转50或62p5_R2_2026-10-05`，NAS同名。R2的45宽、50最低输出、R3根部、35孔、13刻字均为该模块本次实现，非通用标准。

R2构建器仍引用R1目录里的镜架/反射计算辅助代码，重建包中需保留依赖；“旧L几何弃用”不等于可以删除整份R1源。现有部分端点检查报告早于刻字修复，继承依据是`glyph_repair_review.json`证明功能主体双向差为零；后续若改功能结构，必须重做相关检查，不能直接沿用旧PASS。

## 有用旧源与注意事项

- `work/cad_io.py`：已有OCP几何和STEP装配辅助函数。
- `work/drawings_20261004/render_drawing.py`、`spec_schema.json`：加工图后端和输入字段。旧`README_backend.txt`的“待完成”是当时快照，不能作为当前交付结论。
- `work/metric_migration_20261005/render_metric.py`：当前公制图纸包装器，调用上述后端；精确HLR在`work/drawings_20261004/hlr_backend.py`。
- `work/metric_migration_20261005/make_cloud_dxf.py`、`work/drawings_20261004/make_onshape_compat.py`：Onshape展示兼容副本，不能替代标准DXF。
- `work/assembly_audit_20261004/onshape_defaults/defaults.json`：用户会话实测Onshape默认孔表；非Web猜测。
- `work/assembly_audit_20261004/16_rework/model/independent_review.json`：16号预放螺丝、销孔/沉孔局部相通的已审特例。
- `work/slm_mount_20261004/post_interface_review.json`：旧柱接口的XY/clock来源；其旧英制高度已被公制柱替代。
- `work/alignment_pin_20261005/manifest_R3.json`：无刻字、带拔出孔的阶梯定位销最新来源；M1保留本体不变。
- `work/camera_mount_20261004/`、`work/isolation_housed_20261004/`、`work/waveplate05_20261005/`：型号研究和早期来源；当前尺寸/STEP仍先看公制清单。
- 原厂图纸/STEP在相应research目录与交付包原厂资料中。按具体型号与哈希查，不因相似文件名直接复用。
- R2之前的爬架R1、R6/更早的63.5 mm交付、原始大量分体设计是历史参考；不能批量重新导入覆盖当前分类。

## 本机运行环境

已用Python解释器：`/Users/wjj/Documents/Codex/2026-09-23/ni/work/cad-venv/bin/python`，含OCP与ezdxf。环境存在时先复用；不把系统python没有OCP误判为工程不可继续。环境失效时查现有运行时/依赖，不静默换库重写模型。

出图后端调用形状如下（用真实、已核实的spec路径与新输出目录替换占位参数）：

```bash
/Users/wjj/Documents/Codex/2026-09-23/ni/work/cad-venv/bin/python \
  /Users/wjj/Documents/Codex/2026-10-03/onshape/work/metric_migration_20261005/render_metric.py \
  /absolute/path/to/verified-spec.json --out /absolute/path/to/new-drawing-output
```

spec中源STEP哈希和局部坐标要匹配。不要为了沿用命令跳过核验，也不要重新运行历史打包脚本把未冻结源发布出去。

PDF渲染工具已存在于`/Users/wjj/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm`，运行时先检查可用性。`integrate_assembly.py JOB.json`默认只验证任务，实际导出需要`--execute`，且JOB输出必须指向新修订目录。

网站是另一工程，`website_handoff.json`只是交接资料；当前skill任务不自动改网站，也不把Onshape/NAS交付宣称为网站已上线。
