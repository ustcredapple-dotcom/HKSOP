# 名义检查JSON

`format`为`zzlab-mirror-nominal-check-v1`，`units`为`mm`。全部路径相对JSON；输出为新文件，不改输入。`assemblies`数组各项：

- `id/path/sha256`：实际命名STEP及固定SHA。
- `expectedLeafNames`：全部物理及审查叶名称，严格核对重复/遗漏。
- `nonPhysicalReviewLeafNames`：只列非物理审查着色体；`reviewExclusionReason`说明。不能排除必要支撑或五金。
- `singleSolidLeafNames`：列全部独立加工件，检查每叶恰好一个连通实体。商业参考允许其源中的合法多实体，但不能借此放过加工件断裂。
- `keepouts`数组：`id/originMm/axis/radiusMm/lengthMm`定义圆柱；起点/轴向长度须实际量取，覆盖最远物理件。检查器不会自动证明包络范围充分。
- 可选`coplanarGroups`数组：`id/leafNames/bound/datumOffsetMm/expectedPlaneMm/toleranceMm`；至少二叶，bound0..5分别对应xmin/ymin/zmin/xmax/ymax/zmax。共用同款电机边界基准加offset求安装平面；tolerance是数值阈值，不是制造公差。

`intersectionVolumeToleranceMm3`默认1e-6；数值原因可记录调整，不能为侵入通过扩大。

```json
{
  "format":"zzlab-mirror-nominal-check-v1","units":"mm",
  "assemblies":[{
    "id":"my-mirror","path":"models/review.step","sha256":"替换为实际SHA256",
    "expectedLeafNames":["frame","servo-L","servo-H","support","review-cylinder"],
    "nonPhysicalReviewLeafNames":["review-cylinder"],
    "reviewExclusionReason":"非物理通光保护着色体",
    "keepouts":[{"id":"rear","originMm":[0,-150,62.5],"axis":[0,1,0],"radiusMm":12.7,"lengthMm":120}],
    "coplanarGroups":[{"id":"motors","leafNames":["servo-L","servo-H"],"bound":2,"datumOffsetMm":4.5,"expectedPlaneMm":137.5,"toleranceMm":0.00001}]
  }]
}
```

这是格式示例，孔径/区间不能照抄。单位依据源资料显式确认；检查器不从形状自动判inch/mm。若单位冲突先纠正并保留转换证据。
