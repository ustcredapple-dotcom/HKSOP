# 命令参考

[English](commands.en.md)

在仓库根目录执行。新电脑先按首页安装运行依赖，并准备可选的 CAD/Node.js 环境。

```sh
python3 hksop.py catalog check
python3 hksop.py catalog build
python3 hksop.py catalog list
python3 hksop.py runtime build --profile editor
python3 hksop.py serve --profile editor --port 18945
python3 hksop.py package check /path/to/new-package
python3 hksop.py package stage /path/to/new-package --collection custom
python3 hksop.py package adopt runtime/staging/<stage-id>
```

`<stage-id>` 使用 stage 返回的实际值；标准包将 custom 改为 standard。暂存后库发生变化时，重新 stage 再 adopt。示例工程位于 projects。

当前精选范围已经包含所选元件的现用配套图纸。某件资料不全或制造尚未验收时，继续保留该条目的真实状态，不能用文件复制代替验收。

GitHub 目标为私有仓库 ustcredapple-dotcom/HKSOP。config/local-environment.json 仅记录本机解释器路径，换电脑时按 example 配置；缺省使用当前 Python，命令行追迹从 PATH 查找 Node.js。
