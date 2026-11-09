# 元件包起点

[English](README.en.md)

复制整个目录到独立工作目录，修改 `packageId`、记录 ID、名称和型号。这个最小模板只登记物料，不虚构安装孔、光学面或 CAD。需要可摆放套件时，参考 `library/standard/` 中的同类套件，把 kits 记录和相关零件放入新包，替换身份并按实际设计修改接口、光路和 BOM。

在 `package.json` 的 `assets` 中登记实际文件的相对路径、运行目标和 SHA256，然后按[入库指南](../../../docs/component-intake.md)检查、暂存和采用。模板本身没有登记进元件库。
