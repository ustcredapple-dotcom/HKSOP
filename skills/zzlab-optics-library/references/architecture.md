# 架构与维护入口

项目根目录由调用者提供，含 `app.py`、`catalog.json`、`library/manifest.json` 与 `tools/library.py`。技能安装位置不等于项目位置。

## 数据流

```mermaid
flowchart LR
  Sources[Onshape / 厂家资料 / 用户报告] --> Package[元件导入包与审核证据]
  Package --> Stage[隔离候选与校验]
  Stage --> Source[library 结构化真源]
  Source --> Build[确定性构建]
  Build --> Catalog[catalog.json 运行目录]
  Source --> Index[资产 / 交互 / 缺口索引]
  Catalog --> App[画布 / 光路 / BOM]
  Assets[assets 与 static 资源] --> App
  App --> Project[用户工程与账号购物车]
```

目录源、派生目录和用户状态分别维护。`catalog.json` 仍是前后端兼容边界；本次结构化不会改原 ID、安装位置、API、用户工程版本或购物车数据库。

## 模块职责

| 层 | 入口 | 职责 |
|---|---|---|
| 库定义 | `library/records/`、`catalog-meta.json`、`manifest.json` | 每个对象独立文件，顺序与目录级数据显式登记 |
| 导入与构建 | `tools/library.py` | 模板、包检查、隔离候选、采用、确定性构建、全库审计 |
| 制造与显示资源 | `assets/`、`static/topviews/` | 稳定 URL/资产路径，SHA索引；不按导出数量复制文件 |
| HTTP权限边界 | `app.py`、`access_settings.py` | 请求、同源/身份/角色检查；管理员控制游客权限 |
| BOM/结算/快照 | `bom.py`、`cart.py`、`exports.py`、`shared_kits.py` | 来源BOM、用户选配、账号购物车、模板采购表与制造包 |
| 安装几何 | `layout.py`、`stacked_layout.py`、`registered_boards.py` | 真孔对准、真实轮廓、两层板变换与布局可用性 |
| 垫高/生成件 | `elevation.py`、`laser_adapter.py`、`breadboard.py` 与worker | 高度求解、对应材料清单、参数化板STEP/PDF |
| 前端交互 | `static/app.js` 及 `project-file.js`、`shared-project.js`、测量/工作区模块 | 实例选择、复制拖动、工程与属性浮窗；不持有权威采购身份 |
| 光学计算 | `static/optical-engine.js`、`optical-assembly-engine.js`、`optics_settings.py` | 传播、偏振、三维内部光路、持久化参数校验 |
| 光路语言 | `static/optical-interaction-language.js`、`optical_interaction.py` | 目录中的版本化 JSON；入光条件、白名单物理动作和出光分支；前后端均拒绝非法定义 |
| 发布与回退 | `deploy_support.py` | 先协议构建检查，再原有权限/导出测试与版本发布、NAS同步 |

新增常规元件只改库记录、资源和证据。只有新物理能力或新交互类型才修改计算/UI代码，并补充相应协议和回归。不要为新的镜片复制一套画布或购物车实现。

## 兼容与历史脚本

根目录及 `qa/` 中已有 build/register/patch 脚本记录不同历史批次；它们不是当前通用导入入口。有些脚本硬编码旧目录数量、固定日期或快照 SHA，只适合复现对应历史验收，不应为使其“通过”而改新库。复用其几何算法时，先在隔离目录运行，再将产物经统一入口导入。

旧文档中的历史规则可能早于用户修订。交互事实先核对当前代码与本技能的交互协议；特别是8孔只需4孔对齐、沉孔不要求2mm净距、棕色真实轮廓、桌子不出大板以及12.5mm高度目标。协议发现与代码不一致时记录问题，不能把文档修改伪装成功能已实现。

## 本机部署定位（不是通用路径）

当前开发项目：`/Users/wjj/Documents/Codex/2026-09-23/ni/work/optics-kits`。
当前服务：`/Users/Shared/ZZLAB/OpticsKits/current`；独立用户状态位于该服务的 `data/`。
NAS发布副本：`/Volumes/ZZLab_001/ZZLAB Web/Mac service/10_Optics_Kits`；用户交付：`/Volumes/ZZLab_001/Wang Junjie/模块化光路`。

在其他机器上重新确认这些位置和工具能力，不把上述路径写入记录、资产 URL 或 portable package。没有部署环境时仍可完成候选包与本地验收，并准确报告未上线状态；不要另建一个冒充正式站的站点。
