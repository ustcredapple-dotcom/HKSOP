# 工作区配置

[English](README.en.md)

`distribution.json` 记录当前精选范围与私有 GitHub 目标；当前允许提交所选元件的 STEP、俯视图、三视图和配套图纸。`workspace.json` 记录默认构建与运行入口，`retention-policy.json` 记录版本保留规则。

需要指定解释器时，把 `local-environment.example.json` 复制为 `local-environment.json`，填写实际 `runtimePython`、`cadPython` 和 `node` 路径。该本机文件被 Git 忽略，不把个人机器路径写进共享配置。
