# Library

当前编辑源为registry.json列出的独立package.json和records文件。standard是通用套件，components是共用采购/制造零件，modules是组合模块，boards是本副本所需板型，custom仅收录本次所选工程必需的附加定义。

assets/sha256保存STEP和俯视渲染的唯一实体；各元件包的cad/rendering提供根目录内部的相对链接。resource-map.json记录包与资源的对应关系。

运行 `python3 hksop.py catalog build` 生成统一支持清单、搜索目录和当前构建数据。snapshots/web-current只是现行兼容索引，不保存历史库。

三视图和加工/打标图纸按用户要求不包含。记录中的这些运行文件入口为空，制造要求仍需在实际交付前补齐。
