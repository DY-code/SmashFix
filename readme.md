# SmashFix

SmashFix 是一个面向动作视频对比的桌面工具，当前版本适配 Ubuntu 22.04 LTS。

项目主要能力：
- 导入参考动作片段和用户动作片段
- 手动对齐或按击球时刻对齐视频
- 逐帧预览和片段裁剪
- 导出对比视频和动作片段

## Ubuntu 22.04 安装说明

### 1. 安装系统依赖

先安装 Python、VLC 和 FFmpeg：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg vlc libvlc-dev libxcb-xinerama0
```

说明：
- `ffmpeg` 和 `ffprobe` 用于导出、裁剪和读取视频信息
- `vlc` 和 `libvlc-dev` 用于应用内视频预览
- `libxcb-xinerama0` 用于部分 Ubuntu 22.04 环境下的 Qt/xcb 运行依赖

### 2. 创建虚拟环境

在项目根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

如果你之前已经安装过 `MoviePy 2.x`，请先卸载再重装：

```bash
pip uninstall -y moviepy
pip install -r requirements.txt
```

## 启动方式

在虚拟环境激活后运行：

```bash
python3 main.py
```

## 运行依赖说明

当前版本只保证 Ubuntu 22.04 LTS 可用。

程序运行依赖：
- Python 3.10 及以上
- PySide6
- python-vlc
- OpenCV
- MoviePy
- NumPy
- Proglog
- FFmpeg 和 FFprobe
- VLC / libVLC

## Wayland 说明

Ubuntu 22.04 默认可能运行在 Wayland 会话下，而当前项目的 VLC 预览使用 X11 窗口嵌入方式。

本项目已在启动时自动尝试设置：

```bash
QT_QPA_PLATFORM=xcb
```

如果你仍然遇到预览窗口黑屏、无法嵌入或 VLC 初始化失败，可以手动执行：

```bash
export QT_QPA_PLATFORM=xcb
python3 main.py
```

## 常见问题

### 1. 提示缺少 `ffmpeg` 或 `ffprobe`

执行：

```bash
sudo apt install -y ffmpeg
```

安装后可用下面命令确认：

```bash
ffmpeg -version
ffprobe -version
```

### 2. 提示 `No module named 'moviepy.editor'`

这通常表示当前环境装到了 `MoviePy 2.x`，而本项目使用的是 `MoviePy 1.x` 接口。

执行：

```bash
pip uninstall -y moviepy
pip install -r requirements.txt
```

### 3. 程序启动时报 VLC 或 libVLC 相关错误

执行：

```bash
sudo apt install -y vlc libvlc-dev
```

如果系统是 Wayland 会话，优先尝试：

```bash
export QT_QPA_PLATFORM=xcb
python3 main.py
```

### 4. 裁剪导出失败

请先确认：
- `ffmpeg` 可以在终端直接运行
- 导出目录有写权限
- 输入视频文件能被 VLC 或 FFmpeg 正常读取

## Python 依赖文件

项目根目录已提供 [requirements.txt](/home/dycc/文档/A-app开发/SmashFix/requirements.txt)，可直接用于 Ubuntu 22.04 环境安装。
