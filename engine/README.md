# Engine

compiler/cli.py 是独立包编译器；入口为根目录 hksop.py。

layout 处理摆放、孔位、支撑、碰撞与板层；optics 处理光学交互；rendering 处理图形；cad 处理 CAD 辅助；exports 处理 BOM 与交付；apps 保存 Web/编辑器界面；tools 保留原专用工具。

runtime-map.json 指定兼容运行目录中每个文件的源码位置。修改源文件后重建 runtime。原有相对导入继续在生成目录中工作，避免仅移动文件后 import 失效。

此次适配为激光刻字资源校验增加严格的 SHA256 资产路径形式，并让 HKSOP 编辑器库可冻结。既有几何公式和光学算法保持原实现。源码差异与检验回执位于 migration。
