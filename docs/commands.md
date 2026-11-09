# Commands

在HKSOP-github根目录执行：

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

本副本暂不含加工图纸；图纸相关制造导出可能提示缺项，这是当前分发边界。使用项目示例时从projects中选择工程JSON。

GitHub目标为私有仓库ustcredapple-dotcom/HKSOP。config/local-environment.json只供本机解释器定位，移动电脑时按example配置或使用PATH中的Python/Node。
