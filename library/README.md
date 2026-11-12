# 元件库

[English](README.en.md)

编辑源是 `registry.json` 登记的独立 `package.json` 和记录文件。`standard/` 保存标准套件，`components/` 保存共用采购件与制造件，`modules/` 保存组合模块，`boards/` 保存底板定义，`custom/` 保存所选项目需要的定制定义。

`assets/sha256/` 按内容哈希保存模型、俯视图和现用图纸的唯一实体。每个包的 `cad/`、`rendering/` 和 `drawings/` 通过仓库内部相对链接访问资源，`resource-map.json` 记录它们的对应关系。包目录的中英文说明提供记录和文件入口。

在仓库根目录运行 `python3 hksop.py catalog build` 生成统一清单和搜索索引。`snapshots/web-current` 是现行兼容索引，不是历史库。现用图纸保留原修订与验收状态；文件存在不代表已完成新的制造验收。入库方法见[指南](../docs/component-intake.md)。

`history/` 保存旧设计依赖的冻结版本与配套资料入口，引用的共享资源同样受保护。旧工程可解析/渲染这些元件，但它们不出现在新建拖入列表，也不允许通过新增入口新放置。新版和旧版身份明确分离，详见 [旧设计依赖协议](../docs/component-history.md)。
