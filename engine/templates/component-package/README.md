# 元件包起点

复制整个目录到独立工作目录，改 packageId、元件 id、名称和型号。这个模板只登记物料，不虚构光学面、安装孔或 CAD。需要可摆放套件时，参考 library/standard 中最接近的套件，把其 kits 记录和相关组件复制到同一包；更换所有新身份并按真实设计修改接口、光路和 BOM。

在 package.json 的 assets 中登记实际资源相对路径、运行目标路径和 SHA256，再按 docs/component-intake.md 检查、暂存和入库。模板未登记到当前库。
