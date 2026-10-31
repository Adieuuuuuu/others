# 小红书预览图片

目标是保存笔记中实际可访问的图片，按可见幻灯片复刻。无需为这一任务提取笔记正文或评论，也不按文字标称的模板总页数补造图片里未显示的页面。

## 一次读取，再批量保存

1. 用可用浏览器直接打开用户给出的笔记链接；先尝试未登录的公开页面。页面能看到图片时，仅检查笔记轮播的页数、活动页和图片节点。不要把推荐流图片或头像当作原稿。
2. 优先只读当前已加载的 DOM 图片节点；本次验证过 `.note-slider-img img`，可一次读取 `currentSrc`、`naturalWidth`、`naturalHeight` 和 `getBoundingClientRect().x`。页面结构可能变化，先以实际 DOM 为准，不猜测后台接口或构造图片地址。浏览器的页面资源导出若已包含原图，也可直接使用：

   ```js
   const images = await tab.playwright.evaluate(() =>
     Array.from(document.querySelectorAll('.note-slider-img img')).map((img, index) => ({
       index, src: img.currentSrc || img.src,
       width: img.naturalWidth, height: img.naturalHeight,
       x: Math.round(img.getBoundingClientRect().x)
     })).filter(img => img.src && img.width && img.height)
   );
   nodeRepl.write(images);
   ```

   结合当前轮播页码、活动项及节点顺序排除首尾克隆，整理成笔记的实际顺序，并与轮播总数核对。不要仅按 URL 去重而误删笔记中两张真实的相同图片。若有懒加载图片，先在页面切换到对应图片再读取。无法核对完整顺序或数量时记录实际取得的部分。
3. 由实际页面观察到的图片地址直接下载，不转换或放大。可用 [download_xiaohongshu_previews.py](../scripts/download_xiaohongshu_previews.py)：先创建任务 `原始素材/`，使用当前运行环境中带 Pillow 的 Python，将按真实顺序排列的 URL 字符串 JSON 数组通过标准输入传入，并指定 `--out-dir`。例如运行 `python <SKILL_DIR>/scripts/download_xiaohongshu_previews.py --out-dir <TASK_DIR>/原始素材`，再将 JSON 通过标准输入交给该进程。脚本只接受已验证的 `xhscdn.com` 和 `xiaohongshu.com` HTTPS 主机，验证图片格式后按原字节保存，返回顺序、文件名、尺寸、字节数及 SHA-256；同名不同内容会停止而不会覆盖。若实际页面使用其他主机，先核验来源，再选择受支持的方式获取；不要放宽限制或猜地址。不要把签名、Cookie 或笔记 token 硬编码进脚本或持久日志。
4. 有些浏览器的 `pageAssets` 未列出轮播图；`downloadMedia` 可能跳转页面且同一标签不支持并行下载。出现这种情况就用已观察到的图片地址和上面的脚本，不反复尝试同一个失败方式。若因沙箱网络限制失败，确认错误后只为该下载请求使用受支持的权限流程；网络连通性问题按当前项目代理规则检查，勿修改系统代理或全局配置。
5. 图片地址可能过期，每次从当前打开的笔记重新读取。若笔记明确要求登录、验证或页面不可访问，停止并说明；不要绕过验证或伪称已取得图片。保存后核对图片数量、顺序、可打开性和原始字节，再按原有流程逐页裁切和复刻。

该方法已在一个无需登录的三图笔记上验证：浏览器 DOM 暴露三张 1080×1529 预览图，去除轮播克隆后按顺序保存；图片 CDN 在受限沙箱中曾被阻断，正常授权后原字节下载成功。它不保证所有笔记或未来页面结构都无需登录。
