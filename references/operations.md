# 辅助操作

脚本只准备素材和局部修改，不自动理解布局、调用生图或完成目视验收。首次编写幻灯片读取当前 Presentations 技能；生图读取当前 imagegen 技能。先用 load_workspace_dependencies 获取 Python；依赖 Pillow、pypdf、pypdfium2、lxml。PDF 依赖延迟导入，不装全局依赖。

TASK_DIR 是按当前项目规则确定的独立任务制作目录。若项目明确约定 `PPT模板/制作资料/<任务>/`，截图、生图、渲染、脚本、记录和候选均在该处工作；不能再把工作资料写入正式模板库或套用 D 盘默认位置。仅在项目没有相关规则、且位置已明确时使用其他过程目录（如 Windows 的 D:\Codex）。下面命令中的路径均替换为实际绝对路径。

## 素材

~~~text
python prepare_references.py inspect source.png
python prepare_references.py inspect source.pdf
python prepare_references.py render source.pdf --out-dir TASK_DIR/pages --dpi 200
python prepare_references.py render source.pdf --out-dir TASK_DIR/pages --pages 1,3-4
python prepare_references.py crop source.png --regions TASK_DIR/regions.json --out-dir TASK_DIR/crops
~~~

PDF 类型只是候选判断，必须看实际渲染。脚本不 OCR。render 的页面不自动等于幻灯片页数。

regions.json 为数组：每项有 id 与 bbox，例如 {"id":"slide-01","bbox":[55,142,512,399]}。坐标为源图片像素 [left,top,right,bottom]，右/下边界不含，必须在图片范围内。裁片不放大、不锐化、不加圆角，不覆盖已有输出。PDF 页命名 page-001.png。

## 图片替换与逐角几何

~~~text
python pptx_assets.py inspect draft.pptx --out TASK_DIR/inventory.json --extract-dir TASK_DIR/embedded
python pptx_assets.py patch draft.pptx --manifest TASK_DIR/patch.json --output TASK_DIR/patched.pptx --report TASK_DIR/patch-report.json
~~~

使用 inspect 的实际页码和 shape_id；也可给唯一 shape_name。页码从 1 开始；frame_px 和 corners_px 均为 96 DPI CSS 像素。

~~~json
{
  "objects": [
    {"page": 1, "shape_id": "17", "image": "generated/cover.png", "fit": "cover", "corners_px": [35,35,0,0]},
    {"page": 1, "shape_name": "Cover artwork wash", "corners_px": [35,35,0,0]},
    {"page": 5, "shape_id": "8", "corners_px": [0,27,27,0]}
  ]
}
~~~

ID/名称/半径仅是格式示例，必须由当前文件和参考确定。图片路径相对 manifest 所在目录或使用绝对路径；可选 expected_source_sha256 防止误用旧源文件。corners_px 顺序为左上、右上、右下、左下，省略则保留原几何；只修边角时不传 image，不改变取景。

- 输入输出必须不同，输出与报告不能覆盖。对象不能重复指定。
- 仅图片可换位图；普通形状可修边角，用于同步遮罩和手机框。PNG/JPEG 原图按字节嵌入，使用原生 cover 裁切。
- 新图片资源按对象关系隔离，共享旧资源的未选对象不会被误改。仅移除本次替换后确无任何包内关系引用的旧图片，不清理其他未引用资源。
- inspect 会标出 grouped 对象；patch 不直接修改成组对象，需先使用编写工具处理组变换，避免把组内坐标误当页面坐标。
- 报告记录对象、变动包成员及图片哈希，并核对非目标对象/文字；不代替实际渲染。不联网、不安装、不发消息、不删除磁盘旧版本。

## Windows 验收与清理

默认读取磁盘上的最终 PPTX，记录绝对路径与 SHA-256，检查包结构、页数、尺寸、可编辑对象、字体及内嵌资源。制作时的内存预览不能代替最终文件验证。

优先使用真实 PowerPoint 引擎无窗口后台导出，并逐页目视对照参考：

- 使用可用的 PowerPoint 自动化实例；文稿以只读方式打开且不创建窗口，例如 `Presentations.Open(inputPath, -1, 0, 0)`（ReadOnly=True、Untitled=False、WithWindow=False）。导出前核对该文稿 `Windows.Count = 0`，逐页调用 `Slide.Export(path, "PNG", width, height)`；尺寸按实际画布比例确定。
- 只关闭本轮打开的隐藏文稿，不关闭用户已有文稿，不对有用户文稿的应用调用 `Quit`。编辑、另存、关闭、重开与读回验证使用独立临时副本，不改写最终候选。
- 不调用窗口激活、焦点切换、鼠标键盘模拟、放映或 `Visible=True`；不得用切换、最小化用户窗口来伪装后台。需要启动脚本宿主时使用隐藏窗口方式。实例初始化不能保证静默、出现交互提示或导出失败时，停止该路径并记录原因，不自动转前台验收。
- 回执记录最终文件路径与哈希、引擎和版本、输出路径、页数与尺寸、文稿窗口数及实际完成的检查。入库按原字节复制并核对哈希，确保交付文件与受验文件一致。

通用后台渲染可用于快速检查，或原生引擎不可用时备用；同样重新导入最终 PPTX 并逐页导图。注明实际引擎、失败原因及未验证的范围，不能称为原生 PowerPoint 验证或宣称完全等价。无需每次重复双路径对比；发现渲染差异时按具体问题核验。本机静态导图不覆盖跨设备缺失字体、动画播放、复杂媒体或其他软件版本。

未经用户明确要求，不在前台启动、切换或操控 PowerPoint；一般的制作、可打开性检查或验收要求不构成前台操作授权。PowerShell Constrained Language Mode 可能限制 `New-Object -ComObject`；停止盲目重试。CScript/VBScript 的正常 Office 自动化曾在本机通过上述无窗口导图与副本编辑重开验证，仍需在当前任务核对可用性；中文路径脚本可用 UTF-16。遵守工具审批，不修改系统安全策略或全局配置。

候选默认 PPTX；完成并通过验证后，按用户已有授权及当前项目规则入库。已有默认入库授权且目标库明确时，无需逐套重复确认；其他资料仍在制作区。同名已有文件或用户编辑不擅自覆盖。入库与清理分开判断。明确确认并授权清理后，核对终稿与原件哈希、生成绝对路径清单，原生 PowerShell 使用 LiteralPath 删除该清单。不得先枚举路径再拼成其他 shell 删除命令，不动其他模板、原始素材和全局缓存。
