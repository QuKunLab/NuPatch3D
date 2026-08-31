**CellRefine-3D交互式可视化插件操作手册**

### **一、插件概述**
CellRefine-3D 是一款基于 napari
三维可视化平台开发的细胞分割精修插件，面向三维显微镜图像的标注后处理。研究人员加载原始荧光图像与预分割标签图像（TIFF
格式）后，可在 napari
原生的二维/三维视图环境中，结合维度导航、三维旋转、画笔/橡皮擦/颜料桶等基础标注能力，使用本插件执行局部区域提取、欠分割修复（平面分割
/ GMM 分割 /
连通域重标号）、过分割合并、基于图像密度的边界修复、以及基于分水岭的丢细胞检测。插件支持无限步撤销与重做，并可将完整编辑历史序列化保存为
JSON 日志，实现任意时刻的体素级复原与可追溯分析。

### **二、运行环境**
• 操作系统：Windows 10 或 Windows 11
• 硬件建议：Intel 或 AMD 处理器（2.5 GHz 以上），16 GB 内存，512 GB
硬盘

• 显示要求：支持 WebGL 或 OpenGL 的显卡及驱动

### **三、数据加载与图层准备**

![图 1
数据加载控制面板](docs/images/media/image1.png){width="3.076388888888889in"
height="3.56875in"}

**3.1加载图像与标签\**
启动 napari，通过菜单栏 File → Open Files
加载原始荧光图像（TIFF）与预分割标签图像（TIFF）；或将文件直接拖入
napari
窗口完成加载。加载成功后，左下方面板会显示两个图层：Image（原始图像）与
Labels（预分割标签）。

![图 2 插件启动控制面板](docs/images/media/image2.png){width="4.7in"
height="2.5166666666666666in"}

**3.2启动 CellRefine-3D 插件**\
点击菜单栏 Plugins → CellRefine3D (CellRefine3D)，插件面板将停靠在
napari 窗口右侧。

**3.3确认图层映射**\
插件启动后，Cell Bounding Box Extraction 区域的 Label Layer 与 Image
Layer (Reference) 下拉框会自动识别 napari 中的可用图层。请手动核对：\
• Label Layer 必须对应预分割标签图层（Labels 类型）；\
• Image Layer (Reference) 必须对应原始荧光图像图层（Image 类型）。\
若存在多个同类型图层（例如加载了多组标签），请在下拉框中手动切换至当前需要编辑的目标图层。

![图 3
插件基础设置面板](docs/images/media/image3.png){width="4.977777777777778in"
height="2.053472222222222in"}

**3.4配置插件工作环境**\
在开始任何编辑操作前，建议先完成以下基础设置：\
• 界面布局：点击插件顶部 Settings 区域的 Dock Right
按钮，可将插件面板固定到 napari 主窗口右侧。\
• 字体调节：如在高分辨率显示器上操作，可通过 Font Size
数值框实时调节插件界面字体大小，数值即时生效。\
• JSON 日志路径：点击 Select JSON Save Path
指定操作日志的保存位置。该文件用于记录所有编辑历史与 Commit
快照，是实现后续回溯与复原的关键；默认文件名与当前 Image Layer
同名，强烈建议在标注开始前完成设置。设置完成后，Current JSON Path
文本框会显示当前生效的绝对路径。

![图 4
载入数据后软件主界面（三维视图）](docs/images/media/image4.png){width="5.761805555555555in"
height="3.6104166666666666in"}

**3.5确认数据方位**\
利用 napari 左下角的滑块浏览不同切片，或点击 2D / 3D
按钮切换二维/三维视图进行旋转观察，确认细胞分布与预分割质量。napari
基础视图操作详见其官方文档。

![图 5
载入数据后软件主界面（二维视图）](docs/images/media/image5.png){width="5.759722222222222in"
height="3.6055555555555556in"}

### **四、细胞邻域提取（Cell Bounding Box Extraction）**

![图 6 Cell Bounding Box
Extraction面板](docs/images/media/image6.png){width="5.239583333333333in"
height="1.90625in"}

插件所有精修操作均围绕局部邻域（Bounding
Box）展开。用户从全局标签中指定目标细胞，裁剪出包含该细胞的局部立方体，后续的分裂、合并、边界修复与手动修正均在此局部区域内完成，避免误改全局其他细胞。

**4.1 计算细胞中心**

在插件面板 Cell Bounding Box Extraction 区域，点击 Calculate Cell
Centers。插件将为全局标签图中所有非零标签计算三维空间中心坐标，并建立标签索引。

计算完成后，插件会自动根据当前 Label ID 对应细胞的实际直径，将 Box Size
初始化为直径的 2
倍，以确保裁剪区域既能完整包裹目标细胞，又不过度包含无关邻域。

**4.2 设定目标标签与裁剪尺寸**

在 Label ID 输入框中填入需要编辑的目标标签编号，或通过 Previous / Next
按钮按标签中心列表顺序前后切换。插件支持键盘快捷键快速导航：按 A
键切换到上一个标签，按 D 键切换到下一个标签。在 Box Size
数值框中确认或手动调整裁剪立方体的边长（单位：像素）。

**4.3 提取局部编辑区域**

点击 Extract Bounding
Box，插件从全局标签与原始图像中同步裁剪出以目标细胞为中心的局部区域，并在
napari 中生成两个新图层：

• 原图名-Crop：局部原始图像（Image
类型），供边界修复与丢细胞检测时参考图像密度；\
• 原图名-LabelFix：局部可编辑标签（Labels
类型），所有后续精修操作均在此图层上进行。

提取完成后，插件会自动取消 Global View
勾选，将原始全局图层从视图中移除，仅保留局部 LabelFix 与 Crop
图层，防止全局其他细胞干扰局部编辑。此时可利用 napari
基础视图功能旋转、缩放或逐层浏览该局部区域，确认分割质量。

![](docs/images/media/image7.png){width="5.473611111111111in"
height="3.4145833333333333in"}

图 7 提取细胞邻域后软件界面

**4.4 视图标签过滤**

View Labels 输入框中填写需要保留显示的标签编号（以空格分隔），点击 Apply
生效。Apply 执行后会自动激活 Focus 模式：此时仅保留 View Labels
中指定的标签可见，其余标签隐藏；若 View Labels 留空，则默认仅当前 Label
ID 指定的标签可见。

Focus
复选框是一个独立的显示开关------取消勾选即恢复显示全部标签，再次勾选则回到聚焦状态。按快捷键
F
可在聚焦与全部显示之间快速切换，便于在局部分析与整体观察之间灵活跳转。此外，按
Shift + R 可在\"显示全部标签\"与\"仅 View Labels 指定标签\"之间切换，与
Apply 按钮效果等价

![图 8
视图标签过滤后软件界面](docs/images/media/image8.png){width="5.761805555555555in"
height="3.6125in"}

**4.5 全局视图切换**

如需在编辑过程中随时对照全局原始数据，可勾选插件顶部 Settings 区域的
Global View 复选框，原始全局 Image 与 Labels 图层将重新显示于 napari
视图中。再次取消勾选则恢复仅显示局部 LabelFix 与 Crop 图层。

**4.6 手动修正与原生标注工具**

提取局部 LabelFix 图层后，用户可随时使用 napari 原生的
画笔（Paint）、橡皮擦（Erase）、颜料桶（Fill）
等标注工具对分割结果进行手动微调。这些原生操作与插件的算法修复功能完全兼容，可穿插使用：例如，先用橡皮擦擦除粘连区域中两细胞之间的错误桥连体素，将其变为非连通状态，再执行
Connected Components
Split（5.4）实现精确分离；或在边界遗漏处用画笔补全细胞轮廓，再执行
Boundary Fix（第七章）进行密度约束的平滑重建。

所有原生标注操作均被纳入插件统一的 Undo / Redo 栈（9.1）与 Commit
提交流（9.2），并完整记录于 JSON
操作日志（9.4）中，可实现体素级回溯与复原。napari
原生标注工具的具体使用方法详见 napari 官方文档。

### **五、欠分割修复（Under-segmentation Split）**

欠分割是指多个独立细胞被错误地标记为同一个标签。CellRefine-3D
提供三种修复模式：基于几何平面的 Plane 分割、基于高斯混合模型的 Auto
自动分裂，以及由用户指定初始中心的 Manual 手动分裂。三种模式共用同一组
Target Labels，并均可配合 Connected Components Split 进行后处理校正。

在插件面板 Cell Boundary Refine 区域的 Under-segmentation (Split)
子面板中，通过 Mode 下拉框切换模式。

![](docs/images/media/image9.png){width="5.21875in" height="1.6875in"}

图 9 Under-segmentation fix 面板

**5.1 Plane 模式（平面分割）**

适用于形态上可被某一平面清晰分离的粘连细胞。

**5.1.1设定目标标签**\
在 Target Labels 输入框中填写需要分割的标签编号（空格分隔，如 114
514）。

**5.1.2初始化平面位置**\
点击 Draw a Plane。若当前尚未放置平面基准点，插件会先在 napari
左下角面板中创建 Plane Label Splitting-Points
图层（蓝色点），并自动激活该图层进入添加模式，同时提示切换至 2D
视图。此时用户在目标细胞所在位置点击鼠标，插件即以此点击位置为平面经过中心，自动计算默认法向量（垂直于当前
2D 视图切片），并在面板中依次新增 Plane Label
Splitting-Shapes（深灰色半透明矩形平面与黄色法向量箭头）和
Plane-Spherical-Axes（红绿蓝虚线坐标轴）两个辅助图层，同时在 3D
视图中实时渲染出分割平面与方位参考轴。插件面板中的 X/Y/Z 与 Phi/Theta
数值框也会自动同步为当前平面参数。上述三个辅助图层用于交互式辅助定位，按快捷键
Shift + C 一键清理点、坐标、平面和图层(9.3)

**5.1.3微调平面方位**\
通过 X(Red) / Y(Green) / Z(Blue) 数值框调节平面经过点的空间坐标，通过
Phi / Theta 数值框调节平面法向量的球坐标角度。每次参数变化后，3D
视图中的半透明矩形平面与黄色法向量箭头会实时更新，直至平面恰好位于两细胞之间的粘连界面。

**5.1.4执行分割**\
点击 Split by
Plane。插件将位于平面法向量正方向一侧的体素赋予递增的新标签
ID，另一侧保留原标签。分割完成后，可在 2D/3D
视图中验证两细胞是否已被正确分离。

![](docs/images/media/image10.png){width="5.761805555555555in"
height="3.6152777777777776in"}

图 10 平面构建与调整

图 11 平面分割结果示例图

![图 11
平面分割结果示例图](docs/images/media/image11.png){width="5.761805555555555in"
height="3.6083333333333334in"}

**5.2 Auto 模式（GMM 自动分割）**

**5.2.1设定算法参数**

• Sampling Rate：体素采样比例（默认 0.3），控制参与 GMM
训练的样本量。比例越低速度越快，比例越高精度越稳。

• Split Dist：主轴长度分裂阈值（默认
10）。当某标签内点云的主轴长度超过该值时，插件会沿主轴方向将其分裂为两个子簇。

• Merge Dist：高斯中心合并阈值（默认 3）。当两个 GMM
高斯分布的中心距离小于该值时，会被合并为一个细胞。

**5.2.2设定目标标签**\
在 Target Labels
输入框中填写需要自动重分割的标签编号（空格分隔）。留空则对 bbox
内所有非零标签执行重分割。

![图 12
Auto模式面板](docs/images/media/image12.png){width="5.0368055555555555in"
height="1.3958333333333333in"}

**5.2.3执行自动分裂**\
点击 Under-segmentation Fix。插件依次执行：分层采样 → GMM 聚类 →
中心合并 → 主轴分裂 → KNN 全图预测。新产生的标签 ID 从全局最大未使用 ID
开始递增，确保不与现有标签冲突。分裂完成后，插件自动更新细胞中心索引。

![图 14 GMM
自动分割后示例](docs/images/media/image13.png){width="2.651388888888889in"
height="2.607638888888889in"}

![图 13 GMM
自动分割前示例](docs/images/media/image14.png){width="2.5104166666666665in"
height="2.6104166666666666in"}

**5.3 Manual 模式（手动指定中心）**

**5.3.1输入或交互式选择中心坐标**\
在 Coords of Centers 输入框中手动填写各细胞中心坐标，格式为
Z,Y,X（空格分隔多组，如 10,20,30 15,25,35）；或点击 Select Coordinates
按钮，插件会创建 GMM-Coordinates
图层（白色点），并自动激活该图层进入添加模式，提示切换至 2D 视图。在 2D
视图中交互式点击放置中心点，插件会自动将 Points
图层中的坐标同步到输入框，并自动识别这些点所在的标签值回填至 Target
Labels。该辅助图层不参与最终分割计算，分割后可按快捷键 Shift + C
一键清理点和图层。(9.3)

![图 15
Manual模式选点示例](docs/images/media/image15.png){width="5.124305555555556in"
height="3.209722222222222in"}

**5.3.2执行分裂**\
点击 Under-segmentation Fix。插件以手动指定的坐标作为 GMM
初始中心，直接对 Target Labels 执行聚类与 KNN
预测，跳过自动合并与分裂步骤。

![图 16
Manual选点分割结果示例](docs/images/media/image16.png){width="4.95in"
height="3.0881944444444445in"}

**5.4 连通域重标号（Connected Components Split）**

若分割结果中存在同一标签内部不连通的\"孤岛\"，均可点击 Connected
Components Split 进行后处理。插件会对 Target Labels
中的每个标签独立执行三维连通域分析，保留最大连通域为原标签，其余连通域按递增
ID 赋予新标签，从根本上消除同一标签跨多个物理细胞的情况。

### **六、过分割合并（Over-segmentation Merge）**

过分割是指单个细胞或同一连通区域被错误地切分为多个独立标签。CellRefine-3D
提供一键合并功能，将多个细碎标签归并为一个，或将误检出的孤立标签直接抹除。

图 17 过分割合并面板

在插件面板 Cell Boundary Refine 区域的 Over-segmentation (Merge)
子面板中操作。

![](docs/images/media/image17.png){width="4.9222222222222225in"
height="0.4583333333333333in"}

**6.1 多标签合并**

在 Label IDs to merge 输入框中填写待合并的标签编号（以空格分隔，如 10 12
15），点击 Label
Merge。插件会将输入的所有标签统一重写为其中数值最小的标签 ID，其余 ID
对应的体素全部归并到该保留标签下，原有标签编号自动失效。

**6.2 单标签抹除**

若输入框中仅填写单个非零标签（如 10），点击 Label Merge
后，插件会将该标签的所有体素置为背景值
0，相当于从分割结果中删除该细胞区域。此操作常用于清除明显误检的噪声碎片或背景残留标签。

![](docs/images/media/image18.png){width="2.9833333333333334in"
height="2.4055555555555554in"}![](docs/images/media/image19.png){width="2.9409722222222223in"
height="2.4340277777777777in"}

图 19 合并后示例图

图 18 合并前示例图

### **七、边界修复（Boundary Fix）**

边界修复用于修正预分割标签与真实细胞荧光轮廓之间的偏差，例如标签边界过度外扩侵占背景，或收缩遗漏了真实的细胞边缘。插件基于局部图像密度场，在限定范围内重新搜索最优边界，并通过形态学后处理生成平滑、连通的细胞掩膜。

![图 20 Boundary
Fix面板](docs/images/media/image20.png){width="4.9118055555555555in"
height="0.8020833333333334in"}

在插件面板 Cell Boundary Refine 区域的 Boundary Fix 子面板中操作。

**7.1 参数说明**

• Percentile：密度阈值百分位（默认
35）。插件以目标细胞内体素的图像亮度分布为基础，取该百分位对应的亮度值乘以
0.9
作为二值化阈值。数值越高，阈值越严格，满足条件的高亮度体素越少，保留区域越小，边界向内收缩；数值越低，阈值越宽松，满足条件的体素越多，保留区域越大，边界向外扩张。若细胞边界过度外扩、包含了过多背景，可适当提高该值以收紧边界；若细胞边界收缩过度、遗漏了真实的弱信号边缘，或希望捕捉向外延伸的突起，可适当降低该值以扩展边界。

• Scaling：边界框缩放系数（默认 1.00）。以目标细胞的原始 bounding box
为基准，按此系数等比例扩大或缩小搜索范围。大于 1.0
时允许算法在更大范围内寻找最优边界，适用于细胞具有细长突起、原始
bounding box 未能完全包裹的场景；小于 1.0
时限制搜索范围，适用于防止边界向邻近细胞过度扩张。建议初次使用时保持默认值。

• Use
Hull：是否启用三维凸包约束（默认勾选）。勾选后，修复范围被限制在原始标签点云的
3D 凸包及其等比例膨胀/收缩区域内；取消勾选则退化为完整的矩形 bounding
box，适用于细胞形状极度不规则、凸包严重失真的场景。

**7.2 执行修复**

确认当前 Label ID
输入框中已填入需要修复边界的标签编号（支持多个标签，以空格分隔）。调整
Percentile、Scaling 与 Use Hull 后，点击 Boundary Fix。

插件依次执行以下流程：

•对局部原始图像进行均值滤波平滑，抑制噪声；

•按 Scaling 系数计算扩展后的 bounding box；

•若启用 Use Hull，构建目标标签的 3D 凸包作为有效 ROI；

•在 ROI 内按 Percentile 阈值筛选高密度体素，提取最大连通域；

•执行形态学闭运算、膨胀、腐蚀、小洞填充与小对象过滤，生成平滑边界；

•将新边界写回 LabelFix 图层，且严格限制在\"原目标区域 +
背景\"范围内，绝不覆盖邻近其他细胞。

修复完成后，建议在 2D 切片或 3D
视图中旋转观察新边界与荧光信号的贴合度。若结果不理想，可调整参数后再次执行Boundary
Fix。此操作也常与画笔、橡皮擦等结合使用。

![图 22 Boundary Fix 使用后示意图（包含两次percentile 60, Scaling
1.30的操作，外加画笔精修）](docs/images/media/image21.png){width="2.9965277777777777in"
height="2.6222222222222222in"}

![图 21 Boundary
Fix使用前示意图](docs/images/media/image22.png){width="2.8222222222222224in"
height="2.6659722222222224in"}

### **八、丢细胞检测（Missing Cell Detection）**

丢细胞检测用于识别预分割标签中遗漏的真实细胞------即荧光图像中存在明显信号团块，但对应位置未被赋予任何标签的背景区域。插件基于分水岭算法，以用户指定的种子点为前景标记，在限定范围内自动生长出新的细胞标签。

在插件面板 Missing Cell Detection 区域操作。

![图 23 Missing Cell
Detection面板](docs/images/media/image23.png){width="5.041666666666667in"
height="0.6666666666666666in"}

**8.1 放置种子点**

点击 Select Seed Point。若尚未创建种子点图层，插件会自动在 napari 中生成
Missing-Cell-Seeds 图层（黄色 Points），并切换至添加模式。此时需在 2D
视图
下，在疑似漏标记的荧光亮点中心逐层点击放置种子点。每个种子点对应一个待检测的新细胞候选区域；可在多个
Z 层放置多个种子点，插件会依次处理。完成丢细胞检测后，可按快捷键 Shift +
C 一键清理点和图层(9.3)

**8.2 参数说明**

•Threshold：背景/前景亮度阈值（默认
500）。原始图像中亮度低于该值的体素被视为背景，在分水岭标记中被强制置为背景标记（值为
2）。数值越高，对荧光信号的要求越严格，仅高亮区域被纳入候选；数值越低，越多的弱信号区域被纳入候选，但也可能引入噪声。需根据图像信噪比调整，建议初次使用时以能清晰区分细胞与背景为准。

•Max Distance：分水岭生长最大距离（默认
10，单位：像素）。以种子点为起点，算法仅在欧氏距离小于该值的邻域内执行分水岭分割。数值越大，允许新标签向周围扩展的范围越广，适用于体积较大的细胞；数值过小可能导致检测出的新区域明显小于真实细胞。

**8.3 执行检测**

确认已在 Missing-Cell-Seeds 图层放置至少一个种子点，且 Threshold 与 Max
Distance 参数合适后，点击 Detect Missing Cell。插件依次执行：

•以各种子点为前景标记（值为 1），以低于阈值的区域为背景标记（值为 2）；

•计算距离变换场（到最近种子点的欧氏距离）；

•以 Max Distance
为半径限制分水岭计算范围，避免无限制生长到远处其他细胞；

•执行分水岭分割，提取各前景标记对应的独立区域；

•将分割结果中前景区域赋予递增的新标签 ID，写回 LabelFix 图层。

每个种子点理论上产生一个新标签，但是产生的标签覆盖区域可能与实际细胞覆盖区域很可能部分不相符，此时需要用Boundary
Fix进一步修复边界。

![](docs/images/media/image24.png){width="5.761805555555555in"
height="3.6055555555555556in"}

图 24 分水岭选点示例

![图 25
分水岭结果示例](docs/images/media/image25.png){width="5.166666666666667in"
height="3.2354166666666666in"}

### **九、交互与回溯（Interaction）**

所有编辑操作------无论是插件算法修复还是 napari
原生标注------均纳入统一的撤销与重做栈中管理，并实时缓存于内存日志。用户可随时回退到任意历史状态，或将阶段性成果提交回全局原始数据，导出为
TIFF 或序列化 JSON 日志以备完整复原。

![图 26 Interaction面板](docs/images/media/image26.png){width="5.125in"
height="0.4479166666666667in"}

**9.1 撤销与重做（Undo / Redo）**

点击 Undo 按钮或按快捷键 Shift +
Z，撤销上一步操作，标签数据恢复到修改前的状态，同时操作日志同步回退。点击
Redo 按钮或按快捷键 Shift + B，恢复刚刚撤销的操作。撤销与重做栈深度为 10
步，涵盖算法修复、手动涂抹等全部修改类型。

**9.2 提交更改（Commit）**

当局部 LabelFix 中的编辑达到可保存的阶段性成果时，点击 Commit
按钮或按快捷键 Shift + S。插件执行以下动作：

•将当前 LabelFix 中的局部标签数据按 current bounding box
位置写回全局原始 Labels 图层；

•自动生成一条 CommitSnapshot 条目，记录该时刻 bounding box
内完整的体素状态、坐标范围、时间戳及图层映射关系；

•将本次会话以来缓存的所有中间操作日志（含原生画笔、橡皮擦、颜料桶事件及算法修复记录）与该
Commit 快照一并追加写入 JSON 日志文件；

•清空内存中的缓存日志，开始新的记录周期；

•自动重新提取当前 Label ID 的 bounding
box，刷新局部视图以继续下一轮编辑。

注意：

•JSON 日志采用追加写入模式，历史记录不会覆盖。

•每进行一步正确的操作，务必进行commit以保存此次操作。

**9.3 清理辅助图层（Remove Aux Layer）**

在使用 Plane 分割、Manual 选点、Missing Cell Detection
或三维视图导航后，napari Layers 面板中可能残留 Plane Label
Splitting-Points、Plane Label
Splitting-Shapes、Plane-Spherical-Axes、GMM-Coordinates、Missing-Cell-Seeds
等辅助图层。点击插件顶部 Settings 区域的 Remove Aux Layer
按钮，或按快捷键 Shift +
C，可一键删除所有由插件创建的辅助图层，并将活动焦点自动重置到当前编辑图层，避免影响后续操作。

**9.4 导出标签（Export Label）**

点击 Export Label，可将当前修改后的标签图层导出为 TIFF
格式。导出时优先保存全局原始标签图层（若已 Commit
写回）。文件名默认在原始图层名后追加 \_refined，保存目录与当前 JSON
路径所在目录一致；若文件已存在，会弹窗询问是否覆盖。当然也可用Ctrl+S或napari原生的File
→ Save Selected Layers实现。

**9.5 应用 JSON 日志（Apply JSON Log）**

当遇到程序异常退出、标签数据意外丢失，或需要完整复现此前的精修流程时，只需保留原始图像与初始预分割标签，配合
JSON 日志即可重建全部工作。点击 Apply JSON Log，选择本插件生成的 JSON
日志文件。插件按时间戳顺序解析其中所有 CommitSnapshot 条目，校验
bounding box
形状与目标图层兼容性后，将每条快照的体素级标签数据精确写回对应的全局
Labels 图层。若 JSON 中记录的原图层名与当前 napari
中的图层名不一致，插件会自动按 bounding box
形状与体素维度匹配候选图层，或弹窗供用户手动选择。
