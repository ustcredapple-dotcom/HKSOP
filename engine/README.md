# 光学协议引擎

[English](README.en.md)

本目录保存 HKSOP 当前软件实现。统一入口是根目录的 `hksop.py`，由 `compiler/cli.py` 处理元件包检查、编译、入库与运行目录构建。

`layout/` 管理摆放、孔位、支撑、碰撞和板层；`optics/` 处理光学交互；`rendering/` 处理渲染；`cad/` 提供 CAD 辅助；`exports/` 处理 BOM 与交付；`apps/` 保存 Web 和编辑器实现。`tools/` 保留专用工具，使用前核对输入与适用范围。

`runtime-map.json` 将这些源文件映射到兼容运行目录。修改源码后重建 runtime，保留运行时需要的相对导入关系。命令见[命令参考](../docs/commands.md)。
