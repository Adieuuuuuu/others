# 按原图重绘

先看裁片。文字、水印、外部圆角蒙版和艺术画面要分开判断；不能机械复制截图的压缩模糊，也不能随意去掉画面内的关键装饰。

~~~text
Use case: precise-object-edit
Asset type: high-resolution standalone artwork for an existing editable presentation.
Input image 1 is the exact visual target and composition reference.
Reconstruct the same image at higher native resolution. Preserve object count,
silhouettes, positions, relative scale, overlap, material, lighting, tonal balance,
crop and field of view. Do not redesign or add objects.
Subject and composition: [按裁片可见事实描述]
Material and light: [描述真实材质与明暗，不只说“更高级”]
Frame: [目标比例、取景和留白]
Restore clean edges and detail lost in the screenshot. Preserve intentional motion
blur or soft lighting. Do not retain blurred screenshot pixels or merely upscale.
Remove baked-in slide text/numbers and the outside frame; these stay editable in PPT.
No new text, logos, watermark or outer corner mask.
[画面内确需保留的装饰，描述数量、颜色、位置和比例]
~~~

光滑灰球可写 smooth satin / frosted glass, no lunar craters, cracks or coarse rock texture。只有原图矿石本身有孔隙才增加孔隙细节，不能把一种材质迁移给其他图。

地形图里本就有荧光黄星号时保留它；如果 PPT 中已有独立星号，则不在位图重复生成。背景上的“03”、小字和下划线属于原生对象时，只生成背后的干净图片。

卡片、手机浮层或海报字盖住配图时，先标注遮挡。重绘只依据可见轮廓与材质补足允许推断的非证据性背景，覆盖卡片仍在 PPT 中原生重建；不要把卡片一起烘焙进新底图。被遮住的真实信息无法从截图恢复。

先检查相似程度，再看分辨率。构图相近但对象、表面和光线明显变化仍需修正。保持原生生成图片字节，用 PPT 自身裁切；不能把插值后的长边像素数当作真实细节，不能为适配比例拉伸图片。
