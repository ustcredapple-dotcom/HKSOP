# 架构说明

[English](architecture.en.md)

本精选副本沿用 HKSOP 的 engine/library/skills/projects 架构。元件定义放在独立包中，由 registry 登记；catalog、entity-index、package-index、HTML 目录和 runtime 由编译器生成。

标准包沿用 standard/modules 分类，共用采购与制造件放在 components。按结构化 BOM、板型和共同协议参数收齐依赖，并加入一分三和 DoublePass 示例需要的定制定义；不是整目录复制所有 custom 内容。准确范围见 selection.json。

当前元件的 STEP、俯视图、三视图、加工图和打标资料按 SHA256 去重，包内提供根目录内部相对链接。项目示例引用库资源，不重复保存整套项目模型、加工包和历史工程。

2026-11-09 用户扩大了分发范围，允许把所选元件对应的现用图纸加入本仓库。资料沿用原修订与验收状态；复制和哈希校验不等于新完成制造审图。当前恢复范围见 cad-restoration.json。

本机 runtime、_build 和解释器配置不作为 Git 源文件。用户随后明确要求 GitHub 仓库公开，当前元件的模型、俯视资源和配套图纸随源码提交。
