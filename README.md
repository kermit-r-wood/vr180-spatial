# VR180 → Apple 空间照片（Windows）

本地离线自动转换：VR180 等距柱状 SBS → 正前方透视双眼 → 自动垂直对齐 → Apple 空间 HEIC。
不调用 Apple 框架、不上传照片、不用 AI 重新生成另一眼。支持单张与文件夹批量转换。

## 快速使用

需要 Windows x64、Python 3.12。首次使用需安装依赖。
新机器在 PowerShell 中执行：

```powershell
.\setup.ps1 -Python 'C:\path\to\python.exe'
```

把 JPG 或文件夹拖到 `convert.cmd` 即可转换。默认输出至项目的 `output` 文件夹。
同名结果不会自动覆盖。命令行可以指定输出位置、FOV、质量和基线：

```powershell
.\.venv\Scripts\python.exe vr180_to_spatial.py 'D:\photos\scene.jpg' --save-eyes

# 文件夹批量：逐张处理；失败项目打印错误并使最终退出码为 1
.\.venv\Scripts\python.exe vr180_to_spatial.py 'D:\photos' --output-dir output\batch

# 其他相机：必须明确投影与真实基线，避免给普通 SBS/鱼眼错误加标签
.\.venv\Scripts\python.exe vr180_to_spatial.py 'D:\photos\scene.jpg' --projection equirect180 --baseline-mm 64 --hfov 80

# 独立重读与解码验证
.\.venv\Scripts\python.exe verify_output.py output\scene.spatial.heic

# 开发测试
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

`--overwrite` 显式允许覆盖已存在输出。`--eye-order rl` 交换左右眼。
`--disparity 0.02` 指定窗口深度调整；省略时根据匹配点近景自动估计。
`--no-align-vertical` 关闭垂直平移校正。`--save-eyes` 额外输出无损左右眼 PNG。

### 改为近景取景

`--pitch` 正值向下、负值向上。下俯 30° 示例：

```powershell
.\.venv\Scripts\python.exe vr180_to_spatial.py 'D:\photos\scene.jpg' --output-dir output\near_down30 --pitch 30 --hfov 88 --width 2400 --height 2400 --save-eyes
```

非零俯仰角会启用基于匹配点的相对相机姿态估计和双眼几何校正。
程序选取无黑边的共同视场，并按实际输出焦距更新 HEIC 内参；因此输出 FOV 可能小于请求值。
若匹配点不足、相机校正过大或裁切过多会报错。请以输出报告中的实际视场为准。

## 输入与输出范围

- 输入为全宽左右并排、每眼 180°×180° 的等距柱状图；组合图片宽高比为 2:1。
- 自动模式只接受带 `EOS VR Utility` EXIF 软件标记的图像；不是仅凭宽高比猜测。
- 自动识别 `RF5.2mm F2.8 L DUAL FISHEYE`，按 Canon 官方规格使用 60 mm 基线。
- 原始双鱼眼、360°、上下排列、半宽 SBS 不受支持，需要先正确处理投影和排列。
- 支持 20°≤请求水平 FOV<90°，以及 `--pitch` 上下取景；取景必须留在原图前半球内。尚不提供左右 yaw 取景。
- 默认每眼 2400×1800、水平 FOV 75°；对齐后裁掉上下等量边缘，实际高度可能略小。
- 保留真实双眼差异；只修正小幅恒定垂直错位，不做可能改变景深的水平配准。
- 当可匹配特征不足或垂直视差过大时停止并报告错误；不把无法验证的图片静默标为成功。
- 输出为 8-bit SDR sRGB、HEVC 4:2:0 双图 HEIC；输入 ICC 转换至 sRGB。未实现 HDR 保留。
- 不复制源照片完整 EXIF/GPS；源路径、哈希、镜头信息和处理参数记录在本地 JSON 报告。
- 完整 180° 不可能保存在单张标准透视空间照片中。原图不修改，输出是中心视角的衍生照片。

输出文件：

| 文件 | 用途 |
|---|---|
| `*.spatial.heic` | 双眼空间照片 |
| `*.spatial.preview.jpg` | 左右并排的二维预览，不能代替立体观看 |
| `*.spatial.json` | 源文件哈希、转换参数、对齐统计和格式验证 |
| `*.spatial.left.png` / `right.png` | 可选无损中间图 |
| `*.spatial.verification.json` | 独立验证脚本的解码、元数据、图像误差报告 |

## HEIC 实现

`pillow-heif/libheif/x265` 编码两张 HEVC 图像。`spatial_heic.py` 写入：

- HEIF `grpl/ster` 分组，实体顺序为左眼、右眼；左眼为主图。
- ImageIO 使用的相机内参 UUID（简化针孔，相对焦距/主点）。
- ImageIO 使用的相机外参 UUID（单位为微米的真实相机基线，单位旋转矩阵）。
- 视差调整 UUID，关联到两眼及立体分组。

旧 `meta` 替换为等长 `free`，新 `meta` 写在文件尾，以保持所有 `iloc` 图像数据偏移不变。
运行时不使用模板照片，也不把参考照片的镜头参数复制进输出。

验证不仅使用本项目解析器，还使用原生 libheif 解析立体分组、相机内参、旋转矩阵，并完整解码两眼。
测试覆盖解析损坏容器、单眼拒绝、像素位置与解析投影公式一致、左右眼不交换、编码媒体偏移、
多组相机参数，以及公开 ImageIO 样例的二进制属性编码。

## 验证状态与限制

自动化测试覆盖透视投影、双目容器和深度估计。已有 Vision Pro 人工测试确认输出可被识别为空间照片，并有一定双目深度；观看效果依素材和构图而异。

空间照片不等于 Spatial Scene：本项目不生成支持头部平移的三维场景。实验性辅助深度注入未观察到明显观看差异，也未完成 Apple ImageIO 深度读取验证，不能视为有效的 Spatial Scene 导入方案。

私人样片、输出和逐次验证记录不随仓库发布。可运行 `make_stereo_test_card.py` 生成合成立体测试卡；`make_aux_depth_experiment.py <spatial.heic>` 为实验工具。

## 网页取景工作台

双击 `framing.cmd`，或运行 `.venv\Scripts\python.exe preview_server.py --open-browser`。
浏览器打开 `http://127.0.0.1:8765`；使用期间保持服务窗口打开。

- 拖动画面或用方向键调整方向，滚轮调整视场；点击原图定位图可跳转。
- “下方近景”预设朝下 30°，便于寻找前景与背景同时入画的构图。
- 支持左右眼、双眼并排、三种画幅，以及 PNG 双眼图和 JSON 取景参数下载。
- 勾选“深度伪色 · 左眼”可显示相对深度：蓝远红近，灰色表示未通过匹配检查。首次开启将缩小后的图片发送到本机回环服务，用球面极线重参数化和双向 SGBM 匹配计算；不上传外部服务、不落盘。色标固定为整张照片有效逆距离的 5%–95% 分位数，拖动取景不会改变色标。假定原图已做双目标定、左右顺序为 LR，不提供米制距离；白墙、反光、遮挡和残余标定误差会造成缺失或误估。切换右眼/双眼模式自动退出伪色，PNG 导出仍为原色。
- 照片仅在本机处理，在线版不上传照片；本地版的深度和 HEIC 处理会将照片发送给本机回环服务。输入须为 2:1 全宽左右并排的 180° 等距柱状图。
- 左右偏转可预览及导出 PNG；现有 HEIC 转换器仅支持左右方向为 0°。满足条件时可复制 PowerShell 转换命令，在项目目录运行。
- 也可直接点击“直接导出空间照片 HEIC”：自选照片需填写实际相机基线，原图经回环地址交给本机 Python 校正及编码，完成后自动下载。最多 100 MB，单次处理一张；几何校验失败时显示错误，不导出未通过检查的 HEIC。临时处理文件自动清理。
- “下载深度伪色图”导出当前构图的左眼深度叠加 PNG；“下载双眼取景图”始终保留原色。
- 网页为未经立体校正的透视构图预览，不是立体显示；后续 HEIC 几何校正可能裁去边缘。JSON 用于记录选择，不能直接作为现有 CLI 的输入。

## 技术依据

- [Apple: Writing spatial photos](https://developer.apple.com/documentation/imageio/writing-spatial-photos)
- [Apple: Spatial metadata](https://developer.apple.com/documentation/imageio/creating-spatial-photos-and-videos-with-spatial-metadata)
- [libheif: cmin/cmex 与 Apple UUID 解码](https://github.com/strukturag/libheif/blob/master/libheif/box.cc)
- [ImageIO 输出参考样例](https://github.com/udibr/fisheye/tree/main/examples)
- [Canon RF5.2mm 官方规格：60mm 基线](https://www.usa.canon.com/support/p/rf5-2mm-f2-8-l-dual-fisheye)

`research` 为本次开发中下载的参考资料，不是运行依赖，不随程序打包。

## GitHub Pages 在线版

访问 https://kermit-r-wood.github.io/vr180-spatial/ 。选择自己的 VR180 图片后，取景、左右眼预览、PNG 与 JSON 导出全部在浏览器完成。不包含私人示例图、统计脚本或外部图片上传。

| 功能 | GitHub Pages | 本地 Python 服务 |
|---|---|---|
| 打开本地图片、调整取景 | 支持 | 支持 |
| PNG / 取景参数导出 | 支持 | 支持 |
| 深度伪色 | 不支持 | 支持 |
| 空间 HEIC 导出 | 不支持 | 支持 |

GitHub Pages 不运行 Python。在线版禁用依赖后端的操作；运行 `framing.cmd` 可使用完整工具。尚未实现浏览器内 HEIC 编码和深度计算。

推送到 `main` 后，GitHub Actions 仅发布 `web/` 目录。仓库 Settings → Pages 的发布源应为 GitHub Actions。

## 隐私与开发

不要提交真实照片、导出结果、含 EXIF/GPS 的素材或本机验证记录。`.gitignore` 排除了媒体、虚拟环境、研究资料及输出；本地 JSON 报告含源路径与哈希，分享前请检查。导出的 HEIC 不复制原图完整 EXIF/GPS。浏览器导出的 JSON 包含所选文件名。

测试使用合成数据，不需要私人样片：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
