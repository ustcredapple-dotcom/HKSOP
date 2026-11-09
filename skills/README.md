# 操作规范

[English](README.en.md)

先读 [HKSOP_CONTEXT.md](HKSOP_CONTEXT.md)，再按任务选择流程。每个目录都有中英文说明；SKILL.md 是执行规范入口。

[标准光学协议入口](hksop-standard-optics/README.md)：定位元件包、项目和交付入口，选择对应业务流程。使用编译器生成清单，不在 skill 中维护另一份支持表。

[元件设计](hksop-component-design/README.md)：设计机械接口、真实光学基准和配套模型；固定局部坐标、柱轴、安装孔与公制光高。完成后交给入库流程，并保留未验收能力。

[元件入库](hksop-component-upload/README.md)：在库外准备包，检查、暂存并采用，然后重建清单和运行目录。记录稳定 ID、资源 SHA256、BOM 与验收结果；入库本身不代表其他网站或云端已更新。

[加工包](hksop-manufacturing-package/README.md)：冻结工程、元件修订与文件哈希，按加工件整理数量、材料、表面处理、螺纹、模型、工程图和打标资料。保留制造阻塞项，缺项未解除时按审核状态交付。

[客户交付包](hksop-customer-package/README.md)：以选定的当前项目为准，收齐工程 JSON、实际总装、光路展示、BOM 和装配说明。清单记录哈希，说明光学假设、未验收事项和实际云端状态。

[模块化光机设计](zzlab-modular-optics/README.md)：用于万能柱体系的转接件、器件总装、打标和加工工程图。核对真实光学面、公制光高、孔位、工具入口和装配空间。

[电动反射镜架设计](zzlab-motorized-mirror-design/README.md)：用于原厂镜架的电机支撑、驱动连接与模块化转接。核验后通光孔、支撑、运动包络和拆件加工关系，不处理电机固件。

[元件库维护](zzlab-optics-library/README.md)：导入和维护元件资料、真实俯视图、交互定义及采购制造信息。来源、几何、光学和制造分别核验；按当前工作区范围执行外部发布。

[布局转三维](zzlab-optics-json-to-3d/README.md)：将工程 JSON 转为保留源层级的独立器件子装配与总装。核对孔位、光学基准、内部变换及整体姿态；记录实际本地与云端交付。
