# ui/main_window.py
import os
import sys
import copy
import vlc
import cv2
import numpy as np 

# 导入 proglog 用于自定义进度条 logger
from proglog import ProgressBarLogger

from PySide6.QtWidgets import (
    QWidget, QPushButton, QListWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QComboBox, QProgressBar, QCheckBox, QApplication,
    QSplitter, QDialog, QSlider, QMessageBox, QGroupBox, QStackedWidget,
    QTabWidget
)
# pyqtSignal 改为 Signal，添加 QThread
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QRect, QPoint
from PySide6.QtGui import (
    QIntValidator, QPainter, QColor, QPen, QBrush, QImage, QPixmap, QPainterPath
)
from PySide6.QtWidgets import QLineEdit

from moviepy.editor import VideoFileClip, clips_array, ColorClip
from moviepy.video.fx.all import speedx
import shutil
import subprocess

# 系统依赖检测工具函数
def check_command_available(command_name):
    """检查系统命令是否可用。"""
    return shutil.which(command_name) is not None


def check_ffmpeg_available():
    """检查系统是否安装了FFmpeg"""
    return check_command_available('ffmpeg')


def check_ffprobe_available():
    """检查系统是否安装了 FFprobe。"""
    return check_command_available('ffprobe')


def get_missing_runtime_dependencies():
    """返回当前缺失的 Ubuntu 运行依赖。"""
    missing = []
    if not check_ffmpeg_available():
        missing.append("ffmpeg")
    if not check_ffprobe_available():
        missing.append("ffprobe")
    return missing

def check_aspect_ratio_consistency(video_paths):
    """
    检测所有视频的宽高比是否一致（严格模式：误差>1%即不一致）
    
    参数:
        video_paths: 视频文件路径列表
    
    返回:
        (bool, list): (是否一致, 不一致的视频信息列表)
    """
    if not video_paths:
        return True, []
    
    aspect_ratios = []
    video_info = []
    
    for path in video_paths:
        try:
            clip = VideoFileClip(path)
            ratio = clip.w / clip.h
            aspect_ratios.append(ratio)
            video_info.append({
                'path': path,
                'name': os.path.basename(path),
                'size': f"{clip.w}x{clip.h}",
                'ratio': ratio
            })
            clip.close()
        except Exception as e:
            print(f"警告：无法读取视频 {path}: {e}")
            continue
    
    if not aspect_ratios:
        return False, []
    
    # 严格模式：差异 > 1% 即认为不一致
    base_ratio = aspect_ratios[0]
    tolerance = 0.01
    
    inconsistent_videos = []
    for i, info in enumerate(video_info):
        diff_percent = abs(aspect_ratios[i] - base_ratio) / base_ratio
        if diff_percent > tolerance:
            inconsistent_videos.append({
                **info,
                'diff_percent': diff_percent * 100  # 转换为百分比
            })
    
    is_consistent = len(inconsistent_videos) == 0
    
    # 如果不一致，返回所有视频信息以便用户对比
    return is_consistent, video_info if not is_consistent else []

def detect_max_resolution(video_paths):
    """
    检测所有视频的最大宽度和最大高度
    
    参数:
        video_paths: 视频文件路径列表
    
    返回:
        (int, int): (最大宽度, 最大高度)
    """
    max_width = 0
    max_height = 0
    
    for path in video_paths:
        try:
            clip = VideoFileClip(path)
            max_width = max(max_width, clip.w)
            max_height = max(max_height, clip.h)
            clip.close()
        except Exception as e:
            print(f"警告：无法读取视频 {path}: {e}")
            continue
    
    # 返回默认值以防所有视频都读取失败
    if max_width == 0 or max_height == 0:
        return (1920, 1080)
    
    return (max_width, max_height)

def get_video_fps(video_path):
    """使用FFmpeg获取视频帧率"""
    if not check_ffprobe_available():
        print("警告：未检测到 ffprobe，帧率将回退到默认值 30fps")
        return 30.0

    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # 处理分数形式的帧率 (如 "30000/1001")
        fps_str = result.stdout.strip()
        if '/' in fps_str:
            num, den = map(int, fps_str.split('/'))
            return num / den
        return float(fps_str)
    except Exception as e:
        print(f"获取帧率失败: {e}")
        return 30.0  # 默认返回30fps

# -------------------------------------------------------------
# 改进自定义 Logger 类,增强进度回调的可靠性
# -------------------------------------------------------------
class PySideProgressBarLogger(ProgressBarLogger):
    def __init__(self, update_signal_callback):
        super().__init__(init_state=None, bars=None, ignored_bars=None,
                         logged_bars='all', min_time_interval=0, ignore_bars_under=0)
        self.update_signal_callback = update_signal_callback
        # 添加进度缓存，避免重复更新
        self.last_percent = -1

    def callback(self, **changes):
        # 必须先调用父类的 callback 更新内部状态
        super().callback(**changes)
        
        # 遍历所有有变化的进度条
        for bar_name in changes.get('bars', {}).keys():
            # 获取该进度条的完整状态 (包含 total)
            bar = self.bars.get(bar_name)
            
            # 通常 MoviePy 的主进度条叫 't'，但也可能有其他名字
            # 我们只要找到有 index 和 total 的就更新
            if bar:
                index = bar.get('index')
                total = bar.get('total')
                
                if index is not None and total and total > 0:
                    percent = int((index / total) * 100)
                    
                    # 只在进度变化时才更新，避免频繁无效调用
                    if percent != self.last_percent:
                        self.last_percent = percent
                        print(f"Progress: {percent}% ({bar_name})") 
                        self.update_signal_callback(percent)
    
    # 添加bars_callback方法，提供更频繁的进度更新
    def bars_callback(self, bar, attr, value, old_value=None):
        """每次进度条属性变化时都会调用此方法"""
        percentage = (value / self.bars[bar]['total']) * 100 if self.bars[bar].get('total', 0) > 0 else 0
        percent = int(percentage)
        
        if percent != self.last_percent and percent >= 0 and percent <= 100:
            self.last_percent = percent
            print(f"进度更新(bars_callback): {percent}%")
            self.update_signal_callback(percent)


class CropOverlay(QWidget):
    """
    自适应裁剪框覆盖层
    修复：采用 QPainterPath 镂空技术，解决全屏变暗及坐标偏移问题。
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background: transparent;")
        
        # 裁剪比例逻辑
        self.aspect_ratio = 2/3
        self.original_ratio = 16/9 
        self.crop_rect = QRect(0, 0, 100, 150) # 初始占位，将被 set_aspect_ratio 覆盖
        
        self.dragging = False
        self.resizing = False
        self.drag_start = QPoint()
        self.resize_corner = None
        
        self.handle_radius = 6
        self.hit_radius = 15
        self.main_color = QColor(255, 215, 0) 
        self.mask_color = QColor(0, 0, 0, 150) 
        self.video_display_rect = QRect() # 该矩形现在使用相对于自身的坐标 (local)
        
    def set_aspect_ratio(self, ratio_text):
        """设置比例并重置框体大小，尽量保持中心位置"""
        if ratio_text == "2:3 (竖屏)":
            self.aspect_ratio = 2/3
        elif ratio_text == "16:9 (横屏)":
            self.aspect_ratio = 16/9
        elif ratio_text == "原始比例":
            self.aspect_ratio = self.original_ratio
        else:
            return

        old_center = self.crop_rect.center()
        
        # 初始计算尺寸
        w = self.crop_rect.width()
        if w < 50: w = 200 # 防止初始值过小
        h = int(w / self.aspect_ratio)
        
        # 自适应缩放逻辑：防止超出显示区域导致的变形
        if not self.video_display_rect.isEmpty():
            max_w = self.video_display_rect.width() * 0.8
            max_h = self.video_display_rect.height() * 0.8
            
            # 如果计算出的宽高太大，则按比例缩小
            if h > max_h or w > max_w:
                w = max_w
                h = int(w / self.aspect_ratio)
                if h > max_h:
                    h = max_h
                    w = int(h * self.aspect_ratio)

        self.crop_rect = QRect(0, 0, int(w), int(h))
        # 如果旧中心点在视频内，则移动过去；否则居中
        if self.video_display_rect.contains(old_center):
            self.crop_rect.moveCenter(old_center)
        else:
            self.crop_rect.moveCenter(self.video_display_rect.center())
        
        self.constrain_to_video()
        self.update()
    
    def set_video_display_rect(self, rect):
        """设置相对于覆盖层左上角的视频显示区域"""
        self.video_display_rect = rect
        self.constrain_to_video()
        self.update()
    
    def constrain_to_video(self):
        """位置约束逻辑：确保裁剪框不出界"""
        if self.video_display_rect.isEmpty():
            return
        
        r = self.crop_rect
        v = self.video_display_rect
        
        # 限制大小不超标
        if r.width() > v.width():
            r.setWidth(v.width())
            r.setHeight(int(v.width() / self.aspect_ratio))
        if r.height() > v.height():
            r.setHeight(v.height())
            r.setWidth(int(v.height() * self.aspect_ratio))
            
        # 限制坐标在 v 的范围内
        if r.left() < v.left(): r.moveLeft(v.left())
        if r.right() > v.right(): r.moveRight(v.right())
        if r.top() < v.top(): r.moveTop(v.top())
        if r.bottom() > v.bottom(): r.moveBottom(v.bottom())
        
        self.crop_rect = r

    def get_crop_params(self, video_size):
        """计算导出时映射到原视频的像素坐标"""
        if self.video_display_rect.isEmpty():
            return (0, 0, video_size[0], video_size[1])
        
        # 换算比例
        scale_x = video_size[0] / self.video_display_rect.width()
        scale_y = video_size[1] / self.video_display_rect.height()
        
        # 计算相对于显示区域左上角的坐标
        rel_x = self.crop_rect.x() - self.video_display_rect.x()
        rel_y = self.crop_rect.y() - self.video_display_rect.y()
        
        return (max(0, int(rel_x * scale_x)), 
                max(0, int(rel_y * scale_y)), 
                max(2, (int(self.crop_rect.width() * scale_x) // 2) * 2), 
                max(2, (int(self.crop_rect.height() * scale_y) // 2) * 2))
    
    def paintEvent(self, event):
        """
        绘制：路径镂空法。
        1. 绘制半透明遮罩（镂空中心）
        2. 绘制黄色边框和三分线
        3. 绘制手柄
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. 创建镂空路径
        main_path = QPainterPath()
        main_path.addRect(self.rect()) # 整个组件区域
        
        crop_path = QPainterPath()
        crop_path.addRect(self.crop_rect) # 裁剪框区域
        
        # 使用奇偶规则扣掉中心
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.mask_color)
        painter.drawPath(main_path.subtracted(crop_path))
        
        # 2. 绘制辅助线和边框
        r = self.crop_rect
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
        x_step, y_step = r.width() / 3, r.height() / 3
        for i in range(1, 3):
            painter.drawLine(int(r.left() + i * x_step), r.top(), int(r.left() + i * x_step), r.bottom())
            painter.drawLine(r.left(), int(r.top() + i * y_step), r.right(), int(r.top() + i * y_step))
        
        painter.setPen(QPen(self.main_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)
        
        # 3. 手柄
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        painter.setBrush(QBrush(self.main_color))
        corners = [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]
        for corner in corners:
            painter.drawEllipse(corner, self.handle_radius, self.handle_radius)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            corners = {'tl': self.crop_rect.topLeft(), 'tr': self.crop_rect.topRight(),
                       'bl': self.crop_rect.bottomLeft(), 'br': self.crop_rect.bottomRight()}
            for key, corner in corners.items():
                if (pos - corner).manhattanLength() < self.hit_radius:
                    self.resizing, self.resize_corner, self.drag_start = True, key, pos
                    return
            if self.crop_rect.contains(pos):
                self.dragging, self.drag_start = True, pos
    
    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.resizing:
            delta = pos - self.drag_start
            rect = QRect(self.crop_rect)
            if self.resize_corner == 'br':
                w = max(40, rect.width() + delta.x())
                rect.setWidth(w); rect.setHeight(int(w / self.aspect_ratio))
            elif self.resize_corner == 'bl':
                w = max(40, rect.width() - delta.x())
                old_r = rect.right()
                rect.setWidth(w); rect.setHeight(int(w / self.aspect_ratio)); rect.moveRight(old_r)
            elif self.resize_corner == 'tr':
                w = max(40, rect.width() + delta.x())
                old_b = rect.bottom()
                rect.setWidth(w); rect.setHeight(int(w / self.aspect_ratio)); rect.moveBottom(old_b)
            elif self.resize_corner == 'tl':
                w = max(40, rect.width() - delta.x())
                old_r, old_b = rect.right(), rect.bottom()
                rect.setWidth(w); rect.setHeight(int(w / self.aspect_ratio)); rect.moveRight(old_r); rect.moveBottom(old_b)
            self.crop_rect = rect
            self.drag_start = pos
            self.constrain_to_video()
            self.update()
        elif self.dragging:
            delta = pos - self.drag_start
            self.crop_rect.translate(delta.x(), delta.y())
            self.drag_start = pos
            self.constrain_to_video()
            self.update()
    
    def mouseReleaseEvent(self, event):
        self.dragging = self.resizing = False


# -------------------------------------------------------------
# RangeSliderTimeline 类
# -------------------------------------------------------------
class RangeSliderTimeline(QWidget):
    """自定义时间轴：仅支持开始点(Green)和击球点(Red)两个端点拖动"""
    positionChanged = Signal(float)  # 当前播放位置改变信号
    startTimeChanged = Signal(float) # 开始点改变
    hitTimeChanged = Signal(float)   # 击球点改变

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(50)
        self.duration = 1.0
        self.start_time = 0.0
        self.hit_time = 0.5
        self.current_time = 0.0
        
        self.active_handle = None  # 'start', 'hit', 'current'
        self.margin = 15 
        
    def set_duration(self, duration):
        self.duration = max(0.1, duration)
        self.update()

    def set_times(self, start, hit, current):
        self.start_time = start
        self.hit_time = hit
        self.current_time = current
        self.update()

    def _time_to_x(self, t):
        width = self.width() - 2 * self.margin
        return self.margin + int((t / self.duration) * width)

    def _x_to_time(self, x):
        width = self.width() - 2 * self.margin
        t = ((x - self.margin) / width) * self.duration
        return max(0, min(self.duration, t))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        track_y = h // 2
        track_h = 6
        full_width = w - 2 * self.margin

        # 1. 绘制背景轨道
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(50, 50, 50))
        painter.drawRoundedRect(self.margin, track_y - track_h//2, full_width, track_h, 3, 3)

        # 2. 绘制高亮区域（开始时刻 -> 击球时刻）
        x_start = self._time_to_x(self.start_time)
        x_hit = self._time_to_x(self.hit_time)
        painter.setBrush(QColor(74, 144, 226, 120)) # 半透明蓝色高亮
        painter.drawRect(min(x_start, x_hit), track_y - track_h//2, abs(x_hit - x_start), track_h)

        # 3. 绘制刻度
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        step = max(1, int(self.duration / 10))
        for s in range(0, int(self.duration) + 1, step):
            x = self._time_to_x(s)
            painter.drawLine(x, track_y + 8, x, track_y + 12)

        # 4. 绘制端点手柄
        # 开始点 (绿色倒三角)
        painter.setBrush(QColor(46, 204, 113))
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        start_poly = [QPoint(x_start, track_y), QPoint(x_start-8, track_y+15), QPoint(x_start+8, track_y+15)]
        painter.drawPolygon(start_poly)

        # 击球点 (红色倒三角)
        painter.setBrush(QColor(231, 76, 60))
        hit_poly = [QPoint(x_hit, track_y), QPoint(x_hit-8, track_y+15), QPoint(x_hit+8, track_y+15)]
        painter.drawPolygon(hit_poly)

        # 5. 绘制当前播放位置 (黄色细线)
        x_curr = self._time_to_x(self.current_time)
        painter.setPen(QPen(QColor(255, 215, 0), 2))
        painter.drawLine(x_curr, 5, x_curr, h - 5)

    # 禁用端点手柄拖动，仅保留黄色播放头交互 
    def mousePressEvent(self, event):
        """
        处理鼠标按下事件：
        取消对开始点和击球点手柄的判断。点击时间轴任何位置均视为移动播放头(黄色竖线)。
        """
        x = event.pos().x()
        # 直接根据点击位置更新当前播放时刻
        self.current_time = self._x_to_time(x)
        self.active_handle = 'current'
        self.positionChanged.emit(self.current_time)
        self.update()

    def mouseMoveEvent(self, event):
        """
        处理鼠标移动事件：
        仅允许拖动播放头(黄色竖线)。开始点和击球点标记将作为静态参考。
        """
        if self.active_handle == 'current':
            new_time = self._x_to_time(event.pos().x())
            self.current_time = new_time
            self.positionChanged.emit(new_time)
            self.update()

    def mouseReleaseEvent(self, event):
        self.active_handle = None


# 精确帧播放器类
class FrameAccuratePlayer:
    """精确的逐帧播放器（增加信号支持）"""
    def __init__(self, video_widget):
        self.video_widget = video_widget
        self.cap = None
        self.current_frame_index = 0
        self.total_frames = 0
        self.fps = 0
        self.is_playing = False
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.next_frame)
        
        # 回调钩子（避免依赖 MainWindow 信号，使用简单属性）
        self.on_position_changed = None 
    
    def load_video(self, video_path):
        if self.cap: self.cap.release()
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened(): return None, None
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.current_frame_index = 0
        self.show_frame(0)
        return self.total_frames, self.fps
    
    def show_frame(self, frame_index):
        if not self.cap or frame_index < 0 or frame_index >= self.total_frames:
            return False
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_index = frame_index
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            
            # 关键修复：渲染前强制获取 video_widget 此时此刻的真实尺寸
            target_size = self.video_widget.size()
            if target_size.width() < 10 or target_size.height() < 10:
                # 如果尺寸异常（未布局完成），暂时按 800x600 比例计算
                target_size = self.video_widget.parentWidget().size()

            scaled_pixmap = pixmap.scaled(
                target_size, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.video_widget.setPixmap(scaled_pixmap)
            
            if self.on_position_changed:
                self.on_position_changed(frame_index / self.fps if self.fps > 0 else 0)
            return True
        return False
    
    def next_frame(self):
        if self.current_frame_index < self.total_frames - 1:
            self.show_frame(self.current_frame_index + 1)
        else:
            self.stop()
    
    def prev_frame(self):
        if self.current_frame_index > 0:
            self.show_frame(self.current_frame_index - 1)
    
    def play(self, speed=1.0):
        if not self.cap: return
        self.is_playing = True
        interval = int(1000 / (self.fps * speed))
        self.play_timer.start(interval)
    
    def pause(self):
        self.is_playing = False
        self.play_timer.stop()
    
    def stop(self):
        self.pause()
        if self.total_frames > 0: self.show_frame(0)
    
    def get_current_frame_info(self):
        if not self.cap: return None
        return {
            'frame_index': self.current_frame_index,
            'time_seconds': self.current_frame_index / self.fps if self.fps > 0 else 0,
            'total_frames': self.total_frames,
            'fps': self.fps
        }
    
    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None


# -------------------------------------------------------------
# 视频生成线程类，避免阻塞主线程
# -------------------------------------------------------------
class VideoGeneratorThread(QThread):
    """后台线程，用于生成视频而不阻塞UI"""
    # 定义信号
    progress_updated = Signal(int)      # 进度更新信号(百分比)
    status_updated = Signal(str)        # 状态信息更新信号
    finished_signal = Signal(bool, str) # 完成信号(成功/失败, 消息)
    
    def __init__(self, config, output_path):
        super().__init__()
        self.config = config
        self.output_path = output_path
        self.active_clips = []  # 管理创建的clips
        
    def run(self):
        """线程执行的主函数"""
        try:
            self.status_updated.emit("正在生成视频，请稍候...")
            
            # 1. 获取配置参数
            all_paths = self.config['paths']
            ref_paths = self.config['ref_paths']
            user_paths = self.config['user_paths']
            target_duration = self.config['duration']
            video_settings = self.config['settings']
            # 获取当前的对齐模式 (默认为 0: 手动)
            align_mode = self.config.get('align_mode', 0)
            layout_mode = self.config.get('layout_mode', 'horizontal')
            
            # ===== 新增：检测最大分辨率 =====
            target_size = detect_max_resolution(all_paths)
            print(f"[预览生成] 检测到的最大分辨率: {target_size[0]}x{target_size[1]}")
            
            # 2. 定义处理单个视频的函数
            def process_clip(path):
                from moviepy.editor import VideoFileClip
                from moviepy.video.fx.all import speedx
                
                clip = VideoFileClip(path)
                settings = video_settings.get(path, {})
                
                # 兼容"帧数模式"和"时间模式"的参数读取
                trim_start_sec = 0.0
                trim_end_sec = 0.0
                
                # 根据模式明确决定读取哪种参数
                # 模式 1: 击球时刻对齐模式 (优先读取时间参数)
                if align_mode == 1:
                    if "trim_start_time" in settings or "trim_end_time" in settings:
                        trim_start_sec = settings.get("trim_start_time", 0.0)
                        trim_end_sec = settings.get("trim_end_time", 0.0)
                
                # 模式 0: 手动对齐模式 (优先读取帧数参数)
                else:
                    fps = clip.fps if clip.fps else 24.0
                    trim_start_frame = settings.get("trim_start", 0)
                    trim_end_frame = settings.get("trim_end", 0)
                    # 将帧数转换为秒
                    trim_start_sec = trim_start_frame / fps
                    trim_end_sec = trim_end_frame / fps

                # 计算裁剪的绝对时间点
                start_t = trim_start_sec
                end_t = clip.duration - trim_end_sec

                # 执行裁剪
                if end_t > start_t:
                    clip = clip.subclip(start_t, end_t)
                else:
                    print(f"警告: 视频 {os.path.basename(path)} 截断过多，保留原片")

                # 使用 final_duration 自动调整速度
                clip = clip.fx(speedx, final_duration=target_duration)
                
                # ===== 新增：统一分辨率（预览模式：使用默认缩放算法） =====
                if clip.size != target_size:
                    print(f"[预览生成] 缩放 {os.path.basename(path)}: {clip.size} -> {target_size}")
                    clip = clip.resize(newsize=target_size)
                
                return clip
            
            # 3. 处理参考和用户视频
            ref_clips = [process_clip(p) for p in ref_paths]
            user_clips = [process_clip(p) for p in user_paths]
            
            self.active_clips.extend(ref_clips)
            self.active_clips.extend(user_clips)
            
            # 4. 构建网格布局
            from moviepy.editor import clips_array, ColorClip
            
            default_size = target_size  # 修改：使用检测到的最大分辨率

            if layout_mode == 'vertical':
                cols = max(len(ref_clips), len(user_clips))
                ref_row = []
                user_row = []
                for c in range(cols):
                    ref_row.append(ref_clips[c] if c < len(ref_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    user_row.append(user_clips[c] if c < len(user_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                grid = [ref_row, user_row]
            else:
                rows = max(len(ref_clips), len(user_clips))
                grid = []
                for r in range(rows):
                    row_items = []
                    row_items.append(ref_clips[r] if r < len(ref_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    row_items.append(user_clips[r] if r < len(user_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    grid.append(row_items)

            final = clips_array(grid).without_audio()
            
            # 5. 定义进度回调
            def update_progress(percent):
                self.progress_updated.emit(percent)
            
            logger = PySideProgressBarLogger(update_progress)
            
            # 6. 输出视频（预览模式：不使用Lanczos）
            final.write_videofile(
                self.output_path,
                codec="libx264",
                audio_codec="aac",
                fps=24,
                preset="medium",
                logger=logger,
                ffmpeg_params=["-profile:v", "baseline", "-level", "3.0", "-pix_fmt", "yuv420p"]
            )
            
            # 7. 清理资源
            for clip in self.active_clips:
                try:
                    clip.close()
                except:
                    pass
            self.active_clips = []
            
            # 8. 发送成功信号
            self.finished_signal.emit(True, "视频生成完成")
            
        except Exception as e:
            import traceback
            error_msg = f"生成失败: {str(e)}"
            print(traceback.format_exc())
            self.finished_signal.emit(False, error_msg)
            
        finally:
            for clip in self.active_clips:
                try:
                    clip.close()
                except:
                    pass


# -------------------------------------------------------------
# 导出视频线程类（继承自VideoGeneratorThread）
# -------------------------------------------------------------
class ExportVideoThread(VideoGeneratorThread):
    """专门用于导出最终视频的线程，使用更高质量设置"""
    
    def run(self):
        """重写run方法，使用导出专用的高质量参数"""
        try:
            self.status_updated.emit("正在导出最终视频，请稍候...")
            
            # 1. 获取配置参数
            all_paths = self.config['paths']
            ref_paths = self.config['ref_paths']
            user_paths = self.config['user_paths']
            target_duration = self.config['duration']
            video_settings = self.config['settings']
            # 获取当前的对齐模式
            align_mode = self.config.get('align_mode', 0)
            layout_mode = self.config.get('layout_mode', 'horizontal')
            
            # ===== 新增：检测最大分辨率 =====
            target_size = detect_max_resolution(all_paths)
            print(f"[最终导出] 检测到的最大分辨率: {target_size[0]}x{target_size[1]}")
            
            # 2. 定义处理单个视频的函数 (包含参数兼容性修复)
            def process_clip(path):
                from moviepy.editor import VideoFileClip
                from moviepy.video.fx.all import speedx
                
                clip = VideoFileClip(path)
                settings = video_settings.get(path, {})
                
                # 兼容"帧数模式"和"时间模式"的参数读取
                trim_start_sec = 0.0
                trim_end_sec = 0.0
                
                # 根据模式明确决定读取哪种参数
                # 模式 1: 击球时刻对齐模式
                if align_mode == 1:
                    if "trim_start_time" in settings or "trim_end_time" in settings:
                        trim_start_sec = settings.get("trim_start_time", 0.0)
                        trim_end_sec = settings.get("trim_end_time", 0.0)
                
                # 模式 0: 手动对齐模式
                else:
                    fps = clip.fps if clip.fps else 24.0
                    trim_start_frame = settings.get("trim_start", 0)
                    trim_end_frame = settings.get("trim_end", 0)
                    trim_start_sec = trim_start_frame / fps
                    trim_end_sec = trim_end_frame / fps

                start_t = trim_start_sec
                end_t = clip.duration - trim_end_sec

                if end_t > start_t:
                    clip = clip.subclip(start_t, end_t)
                else:
                    print(f"警告: 视频 {os.path.basename(path)} 截断过多，保留原片")

                clip = clip.fx(speedx, final_duration=target_duration)
                
                # ===== 统一分辨率（导出模式：准备使用Lanczos） =====
                if clip.size != target_size:
                    print(f"[最终导出] 缩放 {os.path.basename(path)}: {clip.size} -> {target_size}")
                    clip = clip.resize(newsize=target_size)
                
                return clip
            
            # 3. 处理参考和用户视频
            ref_clips = [process_clip(p) for p in ref_paths]
            user_clips = [process_clip(p) for p in user_paths]
            
            self.active_clips.extend(ref_clips)
            self.active_clips.extend(user_clips)
            
            # 4. 构建网格布局
            from moviepy.editor import clips_array, ColorClip
            
            default_size = target_size  # 修改：使用检测到的最大分辨率

            if layout_mode == 'vertical':
                cols = max(len(ref_clips), len(user_clips))
                ref_row = []
                user_row = []
                for c in range(cols):
                    ref_row.append(ref_clips[c] if c < len(ref_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    user_row.append(user_clips[c] if c < len(user_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                grid = [ref_row, user_row]
            else:
                rows = max(len(ref_clips), len(user_clips))
                grid = []
                for r in range(rows):
                    row_items = []
                    row_items.append(ref_clips[r] if r < len(ref_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    row_items.append(user_clips[r] if r < len(user_clips) else ColorClip(size=default_size, color=(0,0,0), duration=target_duration))
                    grid.append(row_items)

            # 导出时保留音频
            final = clips_array(grid)
            
            # 5. 定义进度回调
            def update_progress(percent):
                self.progress_updated.emit(percent)
            
            logger = PySideProgressBarLogger(update_progress)
            
            # 6. 使用更高质量参数导出（添加Lanczos算法）
            final.write_videofile(
                self.output_path,
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="slow",
                logger=logger,
                ffmpeg_params=[
                    "-sws_flags", "lanczos",  # ← 新增：使用Lanczos高质量缩放算法
                    "-pix_fmt", "yuv420p"
                ]
            )
            
            # 7. 清理资源
            for clip in self.active_clips:
                try:
                    clip.close()
                except:
                    pass
            self.active_clips = []
            
            # 8. 发送成功信号
            self.finished_signal.emit(True, "导出完成")
            
        except Exception as e:
            import traceback
            error_msg = f"导出失败: {str(e)}"
            print(traceback.format_exc())
            self.finished_signal.emit(False, error_msg)
            
        finally:
            for clip in self.active_clips:
                try:
                    clip.close()
                except:
                    pass


# 剪辑器视频导出线程（改用FFmpeg帧精确裁剪）
class ClipExportThread(QThread):
    """
    剪辑器专用的视频导出线程
    
    功能说明：
    - 使用FFmpeg进行帧精确裁剪，避免关键帧导致的时间偏移
    - 支持画面裁剪（crop）
    - 保留音频轨道
    
    参数说明：
    - start_frame/end_frame: 精确的帧编号（由FrameAccuratePlayer提供）
    - crop_params: (x, y, width, height) 裁剪区域坐标
    """
    progress_updated = Signal(int)
    status_updated = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, video_path, start_frame, end_frame, fps, crop_params, output_path):
        super().__init__()
        self.video_path = video_path
        self.start_frame = start_frame  # 使用帧号而非时间
        self.end_frame = end_frame      # 使用帧号而非时间
        self.fps = fps                   # 帧率参数
        self.crop_params = crop_params  # (x, y, width, height)
        self.output_path = output_path
    
    def run(self):
        """
        执行视频导出
        
        修改说明：
        1. 移除所有音频处理相关代码（-af, -c:a, -b:a）
        2. 添加 -an 参数禁用音频
        3. 简化FFmpeg命令结构，避免参数解析歧义
        4. 导出的视频为无音频视频（适合技术动作分析）
        """
        try:
            # 检查FFmpeg是否可用
            if not check_ffmpeg_available():
                self.finished_signal.emit(False, "错误：系统未安装FFmpeg，请先安装FFmpeg")
                return
            
            self.status_updated.emit("正在使用FFmpeg进行帧精确导出（无音频）...")
            self.progress_updated.emit(10)
            
            x, y, w, h = self.crop_params
            
            # 构建FFmpeg命令（简化版）
            cmd = [
                'ffmpeg',
                '-i', self.video_path,
                '-y',  # 覆盖输出文件
            ]
            
            # 构建视频滤镜链
            video_filters = []
            
            # 1. 帧选择滤镜（核心：帧精确裁剪）
            video_filters.append(f"select='between(n\\,{self.start_frame}\\,{self.end_frame})'")
            video_filters.append("setpts=PTS-STARTPTS")
            
            # 2. 画面裁剪滤镜（如果启用）
            if w > 0 and h > 0:
                video_filters.append(f"crop={w}:{h}:{x}:{y}")
            
            # 应用视频滤镜
            cmd.extend(['-vf', ','.join(video_filters)])
            
            # 禁用音频（一行搞定）
            cmd.append('-an')
            
            # 视频编码参数（顺序清晰，无歧义）
            cmd.extend([
                '-c:v', 'libx264',
                '-b:v', '2M',  # 使用比特率控制（2Mbps）
                '-pix_fmt', 'yuv420p',
                self.output_path
            ])
            
            self.progress_updated.emit(30)
            
            # 执行FFmpeg命令
            print(f"执行FFmpeg命令: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='utf-8',  # ← 强制使用UTF-8
                errors='replace'   # ← 遇到无法解码的字符用�替代，而不是崩溃
            )
            
            # 监控进度（通过stderr解析FFmpeg输出）
            stderr_output = []  # 收集错误输出用于调试
            for line in process.stderr:
                stderr_output.append(line)
                
                # FFmpeg进度信息在stderr中，格式如: frame= 150 fps= 30 ...
                if 'frame=' in line:
                    try:
                        # 尝试解析当前处理的帧数（可选的进度优化）
                        parts = line.split('frame=')
                        if len(parts) > 1:
                            frame_str = parts[1].split()[0]
                            current_frame = int(frame_str)
                            total_frames = self.end_frame - self.start_frame
                            if total_frames > 0:
                                progress = 30 + int((current_frame / total_frames) * 60)
                                progress = min(90, progress)  # 上限90%
                                self.progress_updated.emit(progress)
                    except:
                        pass  # 解析失败则跳过，不影响主流程
                
                print(line.strip())  # 输出到控制台便于调试
            
            process.wait()
            
            self.progress_updated.emit(90)
            
            # 检查执行结果
            if process.returncode == 0:
                self.progress_updated.emit(100)
                self.finished_signal.emit(True, f"片段已导出至: {self.output_path}\n（无音频视频）")
            else:
                # 收集完整的错误信息
                error_output = ''.join(stderr_output[-20:])  # 最后20行错误信息
                self.finished_signal.emit(False, f"FFmpeg导出失败:\n{error_output}")
            
        except Exception as e:
            import traceback
            error_msg = f"导出失败: {str(e)}"
            print(traceback.format_exc())
            self.finished_signal.emit(False, error_msg)

# 视频逐帧对比工具类
class VideoComparisonWidget(QWidget):
    """
    视频逐帧对比工具
    
    功能：
    - 左右分屏显示参考视频和用户视频
    - 复用主界面的统一播放控制模块
    - 支持逐帧精确控制
    - 单侧激活机制（蓝色边框高亮）
    """
    
    def __init__(self, ref_paths, user_paths, parent=None):
        super().__init__(parent)
        
        # 保存视频路径列表
        self.ref_paths = ref_paths
        self.user_paths = user_paths
        
        # 播放器数组和激活索引
        self.players = [None, None]  # [0]: 左侧(参考), [1]: 右侧(用户)
        self.active_index = 0  # 默认激活左侧
        
        # 定时器用于播放
        self.play_timer = QTimer()
        self.play_timer.setInterval(100)
        self.play_timer.timeout.connect(self.on_play_timer)
        self.is_playing = False
        self.playback_speed = 0.25
        self.layout_mode = "horizontal"
        
        # 构建UI
        self.build_ui()
        
        # 自动加载第一对视频
        if self.ref_paths and self.user_paths:
            self.load_video(0, self.ref_paths[0])
            self.load_video(1, self.user_paths[0])
            self.update_border_highlight()
    
    def build_ui(self):
        """构建对比界面UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel("视频逐帧对比")
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2D3D;")
        main_layout.addWidget(title_label)

        # ===== 1. 视频显示区域（左右分屏） =====
        self.video_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧视频区域
        self.left_video_label = QLabel("参考视频区域")
        self.left_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_video_label.setStyleSheet("background-color: black; color: gray;")
        self.left_video_label.setMinimumSize(400, 300)
        self.left_video_label.mousePressEvent = lambda e: self.switch_active_player(0)
        self.video_splitter.addWidget(self.left_video_label)
        
        # 右侧视频区域
        self.right_video_label = QLabel("用户视频区域")
        self.right_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_video_label.setStyleSheet("background-color: black; color: gray;")
        self.right_video_label.setMinimumSize(400, 300)
        self.right_video_label.mousePressEvent = lambda e: self.switch_active_player(1)
        self.video_splitter.addWidget(self.right_video_label)
        
        # 设置均分比例
        self.video_splitter.setStretchFactor(0, 1)
        self.video_splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(self.video_splitter, stretch=1)

        # ===== 2. 视频选择区域 =====
        selection_layout = QHBoxLayout()
        
        selection_layout.addWidget(QLabel("选择参考视频:"))
        self.ref_combo = QComboBox()
        for i, path in enumerate(self.ref_paths):
            self.ref_combo.addItem(f"{i+1}. {os.path.basename(path)}", path)
        self.ref_combo.currentIndexChanged.connect(lambda idx: self.on_video_selected(0, idx))
        selection_layout.addWidget(self.ref_combo, stretch=1)
        
        selection_layout.addSpacing(20)
        
        selection_layout.addWidget(QLabel("选择用户视频:"))
        self.user_combo = QComboBox()
        for i, path in enumerate(self.user_paths):
            self.user_combo.addItem(f"{i+1}. {os.path.basename(path)}", path)
        self.user_combo.currentIndexChanged.connect(lambda idx: self.on_video_selected(1, idx))
        selection_layout.addWidget(self.user_combo, stretch=1)
        
        main_layout.addLayout(selection_layout)

    def notify_host(self):
        parent = self.parent()
        if parent and hasattr(parent, "update_unified_playback_ui"):
            parent.update_unified_playback_ui()
    
    def load_video(self, player_index, video_path):
        """加载视频到指定播放器"""
        # 释放旧播放器
        if self.players[player_index]:
            self.players[player_index].release()
        
        # 创建新播放器
        video_label = self.left_video_label if player_index == 0 else self.right_video_label
        player = FrameAccuratePlayer(video_label)
        
        # 设置播放器回调
        player.on_position_changed = self.on_player_position_changed
        
        # 加载视频
        total_frames, fps = player.load_video(video_path)
        
        if total_frames:
            self.players[player_index] = player
            print(f"[对比工具] 加载视频到播放器{player_index}: {os.path.basename(video_path)}")
        else:
            video_label.setText(f"加载失败: {os.path.basename(video_path)}")
        self.notify_host()
    
    def on_video_selected(self, player_index, combo_index):
        """下拉框选择视频时的回调"""
        combo = self.ref_combo if player_index == 0 else self.user_combo
        video_path = combo.itemData(combo_index)
        
        if video_path:
            self.load_video(player_index, video_path)
            self.notify_host()
    
    def switch_active_player(self, index):
        """切换激活的播放器"""
        if index == self.active_index:
            return
        
        # 停止当前播放
        if self.is_playing:
            self.stop_playback()
        
        # 切换激活索引
        self.active_index = index
        
        # 更新UI
        self.update_border_highlight()
        self.notify_host()
        
        print(f"[对比工具] 切换到播放器{index}")
    
    def update_border_highlight(self):
        """更新边框高亮效果"""
        # 激活状态样式
        active_style = "border: 3px solid #4A90E2; background-color: black;"
        # 未激活状态样式
        inactive_style = "border: 1px solid #333333; background-color: black; color: gray;"
        
        if self.active_index == 0:
            self.left_video_label.setStyleSheet(active_style)
            self.right_video_label.setStyleSheet(inactive_style)
        else:
            self.left_video_label.setStyleSheet(inactive_style)
            self.right_video_label.setStyleSheet(active_style)
    
    def get_active_player(self):
        """获取当前激活的播放器"""
        return self.players[self.active_index]
    
    def update_info_display(self):
        """更新信息显示"""
        player = self.get_active_player()
        if not player:
            return None

        return player.get_current_frame_info()
    
    def on_player_position_changed(self, time_seconds):
        """播放器位置变化回调"""
        self.update_info_display()
        self.notify_host()
    
    # ===== 控制按钮槽函数 =====
    
    def on_prev_frame(self):
        """上一帧"""
        player = self.get_active_player()
        if player:
            player.prev_frame()
        self.notify_host()
    
    def on_next_frame(self):
        """下一帧"""
        player = self.get_active_player()
        if player:
            player.next_frame()
        self.notify_host()
    
    def on_play_pause(self):
        """播放/暂停切换"""
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback()
    
    def start_playback(self, speed=None):
        """开始播放"""
        player = self.get_active_player()
        if not player:
            return

        if speed is not None:
            self.playback_speed = speed

        player.play(self.playback_speed)
        self.is_playing = True
        self.play_timer.start()
        self.notify_host()
    
    def stop_playback(self):
        """停止播放"""
        player = self.get_active_player()
        if player:
            player.pause()
        
        self.is_playing = False
        self.play_timer.stop()
        self.notify_host()
    
    def on_play_timer(self):
        """播放定时器（用于检测播放结束）"""
        player = self.get_active_player()
        if not player:
            return
        
        info = player.get_current_frame_info()
        if info and info['frame_index'] >= info['total_frames'] - 1:
            # 播放到末尾，自动停止
            self.stop_playback()
        self.notify_host()
    
    # ===== 进度条槽函数 =====
    
    def on_slider_pressed(self):
        """进度条按下时暂停播放"""
        if self.is_playing:
            self.stop_playback()
    
    def on_slider_moved(self, value):
        """进度条拖动时实时更新画面"""
        player = self.get_active_player()
        if player:
            player.show_frame(value)
        self.notify_host()
    
    def on_slider_released(self):
        """进度条释放"""
        # 可以在这里添加额外逻辑（如果需要）
        pass
    
    def closeEvent(self, event):
        """关闭事件：清理资源"""
        # 释放所有播放器
        for player in self.players:
            if player:
                player.release()
        
        event.accept()

    def refresh_video_lists(self, ref_paths, user_paths):
        """同步主界面导入的视频列表。"""
        self.ref_paths = ref_paths
        self.user_paths = user_paths

        self.ref_combo.blockSignals(True)
        self.user_combo.blockSignals(True)

        current_ref = self.ref_combo.currentData()
        current_user = self.user_combo.currentData()

        self.ref_combo.clear()
        for i, path in enumerate(self.ref_paths):
            self.ref_combo.addItem(f"{i+1}. {os.path.basename(path)}", path)

        self.user_combo.clear()
        for i, path in enumerate(self.user_paths):
            self.user_combo.addItem(f"{i+1}. {os.path.basename(path)}", path)

        self.ref_combo.blockSignals(False)
        self.user_combo.blockSignals(False)

        if self.ref_paths:
            ref_index = max(0, self.ref_combo.findData(current_ref))
            self.ref_combo.setCurrentIndex(ref_index)
            self.load_video(0, self.ref_combo.currentData())
        else:
            self.players[0] = None
            self.left_video_label.setText("参考视频区域")

        if self.user_paths:
            user_index = max(0, self.user_combo.findData(current_user))
            self.user_combo.setCurrentIndex(user_index)
            self.load_video(1, self.user_combo.currentData())
        else:
            self.players[1] = None
            self.right_video_label.setText("用户视频区域")

        self.update_border_highlight()
        self.notify_host()

    def seek_active_player(self, frame_index):
        player = self.get_active_player()
        if player:
            player.show_frame(frame_index)

    def get_active_media_info(self):
        return self.update_info_display()

    def set_layout_mode(self, layout_mode):
        """切换视频对比区排版。"""
        self.layout_mode = layout_mode
        orientation = Qt.Orientation.Horizontal if layout_mode == "horizontal" else Qt.Orientation.Vertical
        self.video_splitter.setOrientation(orientation)
        self.notify_host()


class ClipEditorWindow(QDialog):
    """动作片段剪辑器独立窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("动作片段剪辑器")
        self.resize(1200, 800)
        
        self.video_path = None
        self.frame_player = None
        self.start_time = 0.0
        self.hit_time = None
        self.end_time = None
        self.hit_before_after_ratio = 3.0  # 默认击球前:后 = 3:1
        
        self.export_thread = None
        # 新增：用于精准记录当前导出的文件路径，防止导入时字符串解析出错
        self.current_export_path = None 
        
        self.build_ui()
    
    def build_ui(self):
        """构建优化后的剪辑器UI布局"""
        main_layout = QVBoxLayout(self)
        
        # 1. 顶部：视频预览
        preview_container = QWidget()
        preview_container.setStyleSheet("background-color: #1a1a1a; border-radius: 5px;")
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_label = QLabel("请加载视频")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("color: #666; font-size: 16px;")
        preview_layout.addWidget(self.video_label)
        
        # 裁剪覆盖层
        self.crop_overlay = CropOverlay(preview_container)
        self.crop_overlay.hide()
        
        main_layout.addWidget(preview_container, stretch=10)
        
        # 2. 中间：时间轴
        self.timeline = RangeSliderTimeline()
        self.timeline.positionChanged.connect(self.on_timeline_seek)
        self.timeline.startTimeChanged.connect(self.on_timeline_start_changed)
        self.timeline.hitTimeChanged.connect(self.on_timeline_hit_changed)
        main_layout.addWidget(self.timeline)
        
        # 3. 控制按钮行
        ctrl_bar = QHBoxLayout()
        btn_load = QPushButton("📁 加载视频")
        btn_load.clicked.connect(self.load_video)
        btn_load.setStyleSheet("padding: 5px 15px; font-weight: bold;")
        ctrl_bar.addWidget(btn_load)
        
        ctrl_bar.addSpacing(20)
        
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.clicked.connect(self.play_video)
        ctrl_bar.addWidget(self.btn_play)
        
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.clicked.connect(self.pause_video)
        ctrl_bar.addWidget(self.btn_pause)
        
        ctrl_bar.addWidget(QPushButton("◀", clicked=self.prev_frame))
        ctrl_bar.addWidget(QPushButton("▶", clicked=self.next_frame))
        
        ctrl_bar.addWidget(QLabel("速度:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.1x", "0.25x", "0.5x", "1.0x"])
        self.speed_combo.setCurrentText("0.25x")
        self.speed_combo.currentTextChanged.connect(self.change_speed)
        ctrl_bar.addWidget(self.speed_combo)
        
        ctrl_bar.addStretch()
        self.file_label = QLabel("未选择视频")
        self.file_label.setStyleSheet("color: #888;")
        ctrl_bar.addWidget(self.file_label)
        main_layout.addLayout(ctrl_bar)

        # 4. 设置区域
        settings_layout = QHBoxLayout()
        time_group = QGroupBox("⏱ 时间段定义")
        time_inner = QVBoxLayout(time_group)
        
        h_start = QHBoxLayout()
        h_start.addWidget(QLabel("开始:"))
        self.start_label = QLabel("0.000s")
        h_start.addWidget(self.start_label, 1)
        btn_set_start = QPushButton("📍 设为当前")
        btn_set_start.clicked.connect(self.set_start_time)
        h_start.addWidget(btn_set_start)
        time_inner.addLayout(h_start)
        
        h_hit = QHBoxLayout()
        h_hit.addWidget(QLabel("击球:"))
        self.hit_label = QLabel("未设置")
        h_hit.addWidget(self.hit_label, 1)
        btn_set_hit = QPushButton("📍 设为当前")
        btn_set_hit.clicked.connect(self.set_hit_time)
        h_hit.addWidget(btn_set_hit)
        time_inner.addLayout(h_hit)
        
        h_ratio = QHBoxLayout()
        h_ratio.addWidget(QLabel("前后比例:"))
        self.ratio_input = QLineEdit("3.0")
        self.ratio_input.setFixedWidth(50)
        h_ratio.addWidget(self.ratio_input)
        h_ratio.addWidget(QLabel(": 1  → 结束时刻:"))
        self.end_label = QLabel("自动计算")
        self.end_label.setStyleSheet("color: #2ECC71; font-weight: bold;")
        h_ratio.addWidget(self.end_label, 1)
        time_inner.addLayout(h_ratio)
        settings_layout.addWidget(time_group, 2)
        
        crop_group = QGroupBox("🖼 画面裁剪")
        crop_inner = QVBoxLayout(crop_group)
        h_crop_opt = QHBoxLayout()
        h_crop_opt.addWidget(QLabel("比例:"))
        self.crop_ratio_combo = QComboBox()
        self.crop_ratio_combo.addItems(["2:3 (竖屏)", "16:9 (横屏)", "原始比例"])
        self.crop_ratio_combo.setCurrentIndex(0)
        self.crop_ratio_combo.currentTextChanged.connect(self.change_crop_ratio)
        h_crop_opt.addWidget(self.crop_ratio_combo)
        self.crop_enable_check = QCheckBox("开启裁剪框")
        self.crop_enable_check.stateChanged.connect(self.toggle_crop_overlay)
        h_crop_opt.addWidget(self.crop_enable_check)
        crop_inner.addLayout(h_crop_opt)
        crop_inner.addStretch()
        btn_export = QPushButton("💾 导出片段（帧精确）")
        btn_export.clicked.connect(self.export_clip)
        btn_export.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold; padding: 10px;")
        crop_inner.addWidget(btn_export)
        settings_layout.addWidget(crop_group, 1)
        main_layout.addLayout(settings_layout)
        
        # 5. 底部状态
        footer = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        footer.addWidget(self.progress_bar)
        self.status_label = QLabel("就绪")
        footer.addWidget(self.status_label)
        main_layout.addLayout(footer)

    def load_video(self):
        """加载视频文件并初始化"""
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video (*.mp4 *.mov *.mkv *.avi)")
        if not path: return
        self.video_path = path
        self.file_label.setText(os.path.basename(path))
        if self.frame_player: self.frame_player.release()
        self.frame_player = FrameAccuratePlayer(self.video_label)
        self.frame_player.on_position_changed = self.on_player_time_update
        total_frames, fps = self.frame_player.load_video(path)
        if total_frames:
            QApplication.processEvents()
            try:
                clip = VideoFileClip(path)
                self.crop_overlay.original_ratio = clip.w / clip.h
                clip.close()
            except: pass
            self.frame_player.show_frame(0)
            display_rect = self.update_crop_overlay_geometry()
            duration = total_frames / fps
            self.timeline.set_duration(duration)
            self.timeline.set_times(0, duration, 0)
            current_ratio_text = self.crop_ratio_combo.currentText()
            self.crop_overlay.set_aspect_ratio(current_ratio_text)
            if not display_rect.isEmpty():
                self.crop_overlay.crop_rect.moveCenter(display_rect.center())
            self.status_label.setText(f"视频已加载 | 总帧数: {total_frames} | FPS: {fps:.2f}")
            self.update()
        else:
            self.status_label.setText("视频加载失败")

    def on_timeline_seek(self, t):
        if self.frame_player:
            frame = int(t * self.frame_player.fps)
            self.frame_player.show_frame(frame)
            self.update_frame_info()

    def on_timeline_start_changed(self, t):
        self.start_time = t
        self.start_label.setText(f"{t:.3f}s")
        self.calculate_end_time()
    
    def on_timeline_hit_changed(self, t):
        self.hit_time = t
        self.hit_label.setText(f"{t:.3f}s")
        self.calculate_end_time()

    def on_player_time_update(self, t):
        self.timeline.current_time = t
        self.timeline.update()

    def update_crop_overlay_geometry(self):
        if not self.frame_player: return QRect()
        label_rect = self.video_label.geometry()
        self.crop_overlay.setGeometry(label_rect)
        pixmap = self.video_label.pixmap()
        if pixmap:
            pixmap_size, label_size = pixmap.size(), self.video_label.size()
            scale = min(label_size.width() / pixmap_size.width(), label_size.height() / pixmap_size.height())
            display_width, display_height = int(pixmap_size.width() * scale), int(pixmap_size.height() * scale)
            local_x, local_y = (label_size.width() - display_width) // 2, (label_size.height() - display_height) // 2
            video_display_rect = QRect(local_x, local_y, display_width, display_height)
            self.crop_overlay.set_video_display_rect(video_display_rect)
            return video_display_rect
        return QRect()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_crop_overlay_geometry()

    def play_video(self):
        if not self.frame_player: return
        speed = {"0.1x": 0.1, "0.25x": 0.25, "0.5x": 0.5, "1.0x": 1.0}.get(self.speed_combo.currentText(), 0.25)
        self.frame_player.play(speed)
    
    def pause_video(self):
        if self.frame_player: self.frame_player.pause()
    
    def prev_frame(self):
        if self.frame_player: self.frame_player.prev_frame(); self.update_frame_info()
    
    def next_frame(self):
        if self.frame_player: self.frame_player.next_frame(); self.update_frame_info()

    def update_frame_info(self):
        if self.frame_player:
            info = self.frame_player.get_current_frame_info()
            if info: self.status_label.setText(f"第{info['frame_index']}帧 ({info['time_seconds']:.3f}秒)")

    def change_speed(self):
        if self.frame_player and self.frame_player.is_playing: self.play_video()

    def set_start_time(self):
        if self.frame_player:
            info = self.frame_player.get_current_frame_info()
            if info:
                self.start_time = info['time_seconds']
                self.start_label.setText(f"{self.start_time:.3f}s")
                self.timeline.set_times(self.start_time, self.hit_time or self.start_time, self.start_time)
                self.calculate_end_time()
    
    def set_hit_time(self):
        if self.frame_player:
            info = self.frame_player.get_current_frame_info()
            if info:
                self.hit_time = info['time_seconds']
                self.hit_label.setText(f"{self.hit_time:.3f}s")
                self.timeline.set_times(self.start_time, self.hit_time, self.hit_time)
                self.calculate_end_time()

    def calculate_end_time(self):
        if self.hit_time is None: return
        before_duration = self.hit_time - self.start_time
        if before_duration < 0: return
        after_duration = before_duration / self.hit_before_after_ratio
        self.end_time = self.hit_time + after_duration
        if self.frame_player:
            max_t = self.frame_player.total_frames / self.frame_player.fps
            if self.end_time > max_t: self.end_time = max_t
        self.end_label.setText(f"{self.end_time:.3f}s")
        self.timeline.set_times(self.start_time, self.end_time, self.timeline.current_time, self.hit_time)

    def change_crop_ratio(self, text):
        self.crop_overlay.set_aspect_ratio(text)

    def toggle_crop_overlay(self, state):
        if state == Qt.CheckState.Checked.value:
            self.crop_overlay.show()
            self.update_crop_overlay_geometry()
        else: self.crop_overlay.hide()

    def validate_clip_params(self):
        if not self.frame_player: return False
        if self.hit_time is None or self.end_time is None: return False
        return self.end_time > self.start_time

    def export_clip(self):
        """导出片段"""
        if not self.validate_clip_params(): return
        if not check_ffmpeg_available(): return
        
        default_name = f"{os.path.splitext(os.path.basename(self.video_path))[0]}_clip.mp4"
        save_path, _ = QFileDialog.getSaveFileName(self, "保存片段", default_name, "MP4 文件 (*.mp4)")
        if not save_path: return
        
        # 关键修复：在这里记录纯净的导出路径
        self.current_export_path = save_path
        
        fps = self.frame_player.fps
        start_frame, end_frame = int(self.start_time * fps), int(self.end_time * fps)
        
        if self.crop_enable_check.isChecked():
            clip_test = VideoFileClip(self.video_path)
            video_size = clip_test.size
            clip_test.close()
            crop_params = self.crop_overlay.get_crop_params(video_size)
        else: crop_params = (0, 0, 0, 0)
        
        self.export_thread = ClipExportThread(self.video_path, start_frame, end_frame, fps, crop_params, save_path)
        self.export_thread.progress_updated.connect(self.on_export_progress)
        self.export_thread.status_updated.connect(self.on_export_status)
        self.export_thread.finished_signal.connect(self.on_export_finished)
        self.export_thread.start()

    def on_export_progress(self, percent): self.progress_bar.setValue(percent)
    def on_export_status(self, status): self.status_label.setText(status)

    def on_export_finished(self, success, message):
        """导出完成处理"""
        self.status_label.setText(message)
        if success:
            self.progress_bar.setValue(100)
            reply = QMessageBox.question(self, "导出成功", f"导出成功！\n\n是否将该片段导入到主界面对比列表？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                # 关键修复：直接使用精准记录的路径变量，彻底解决解析失败问题
                output_path = self.current_export_path
                
                import_reply = QMessageBox.question(self, "选择导入位置", "导入到参考列表？\n(选择'No'将导入到用户列表)",
                                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                is_ref = (import_reply == QMessageBox.StandardButton.Yes)
                if self.parent(): self.parent().import_clip_from_editor(output_path, is_ref)
                self.accept()
        else: self.progress_bar.setValue(0)

    def closeEvent(self, event):
        if self.frame_player: self.frame_player.release()
        event.accept()


class MainWindow(QWidget):
    # -------------------------------------------------------------
    # 使用 Signal 替代 pyqtSignal
    # -------------------------------------------------------------
    # 定义一个信号，用于通知主线程播放结束
    vlc_end_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Sync & Layout Tool (VLC Player Version - PySide6)")
        self.resize(1100, 700)

        self.ref_paths = []   # 存储参考动作（左侧）
        self.user_paths = []  # 存储用户动作（右侧）

        # 字典用于存储每个视频的独立设置
        # 结构示例: { "C:/path/to/video.mp4": {"trim_start": 100, "trim_end": 50} }
        self.video_settings = {} 

        # 存储每个视频的击球时刻信息
        # 结构: { "视频路径": {"hit_frame": 帧数, "hit_time": 时间(秒), "before_duration": 前时长, "after_duration": 后时长} }
        self.hit_moments = {}
        
        # 当前对齐模式: 0=手动对齐, 1=击球时刻对齐
        self.current_align_mode = 0
        self.layout_mode = "horizontal"
        self.aligned_target_duration = None

        self.preview_path = "preview.mp4"
        # 缓存上一次生成视频的配置，用于判断是否需要重新生成
        self.last_config = None
        # 判断是否是用户手动点击了停止
        self.is_manual_stop = False

        # 用于存储当前活动的 Clip 对象，以便显式关闭，防止 [WinError 6]
        self.active_clips = []

        # 添加视频生成线程对象的引用
        self.video_thread = None  # 视频生成线程

        # 添加帧播放器实例化（需在build_ui之后） 
        # 注意：实际的初始化将在 build_ui() 之后进行
        self.frame_player = None  # 精确帧播放器（用于击球时刻设置）
        self.is_using_frame_player = False  # 标记当前是否在使用帧播放器

        self.build_ui()
        self.build_vlc()

        # 在UI构建后初始化帧播放器 
        self.frame_player = FrameAccuratePlayer(self.video_widget)

        # 程序启动时自动尝试导入测试视频
        self.auto_load_test_videos()

        missing_dependencies = get_missing_runtime_dependencies()
        if missing_dependencies:
            self.status_label.setText(
                "⚠ 警告：缺少运行依赖 "
                + ", ".join(missing_dependencies)
                + "，部分功能将不可用。请按 readme 安装 Ubuntu 依赖。"
            )
        self.update_unified_playback_ui()

    # -------------------------------------------------------------
    #   VLC 播放组件初始化
    # -------------------------------------------------------------
    def build_vlc(self):
        self.vlc_instance = vlc.Instance("--no-video-title-show")
        self.vlc_player = self.vlc_instance.media_player_new()

        # -------------------------------------------------------------
        if not sys.platform.startswith("linux"):
            raise RuntimeError("当前版本仅支持 Ubuntu 22.04 LTS。")

        # PySide6 的 winId() 返回的是对象，必须强制转换为 int。
        self.vlc_player.set_xwindow(int(self.video_widget.winId()))

        self.vlc_timer = QTimer(self)
        self.vlc_timer.setInterval(200)
        self.vlc_timer.timeout.connect(self.update_preview_status)

        # 监听 VLC 播放结束事件
        events = self.vlc_player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_vlc_end)

        # 将自定义信号连接到主线程的处理函数
        self.vlc_end_signal.connect(self.handle_vlc_end)

    def auto_load_test_videos(self):
        """自动导入当前目录下的 A.mp4 (参考) 和 B.mp4 (用户)"""
        # 获取绝对路径以确保兼容性
        path_a = os.path.abspath("A.mp4")
        path_b = os.path.abspath("B.mp4")
        
        has_loaded = False
        
        # 1. 尝试导入参考视频 A.mp4
        if os.path.exists(path_a):
            try:
                # 简单验证文件有效性
                from moviepy.editor import VideoFileClip
                clip = VideoFileClip(path_a)
                clip.close()
                
                self.ref_paths.append(path_a)
                self.ref_list_widget.addItem(path_a)
                # 初始化设置
                self.video_settings[path_a] = {"trim_start": 0, "trim_end": 0}
                print(f"[自动导入] 参考视频已加载: {path_a}")
                has_loaded = True
            except Exception as e:
                print(f"[自动导入] 加载 A.mp4 失败: {e}")
        
        # 2. 尝试导入用户视频 B.mp4
        if os.path.exists(path_b):
            try:
                from moviepy.editor import VideoFileClip
                clip = VideoFileClip(path_b)
                clip.close()
                
                self.user_paths.append(path_b)
                self.user_list_widget.addItem(path_b)
                # 初始化设置
                self.video_settings[path_b] = {"trim_start": 0, "trim_end": 0}
                print(f"[自动导入] 用户视频已加载: {path_b}")
                has_loaded = True
            except Exception as e:
                print(f"[自动导入] 加载 B.mp4 失败: {e}")
                
        # 3. 如果有视频导入，刷新下拉框
        if has_loaded:
            self.refresh_combo_box()
            self.reset_speed_duration_defaults()
            # 自动选择第一个视频以便立即操作
            if self.manual_video_combo.count() > 0:
                self.manual_video_combo.setCurrentIndex(0)

    def build_ui(self):
        """构建主界面UI。"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- 左侧控制区 ---
        left_panel = QVBoxLayout()

        # 【模块1】动作片段导入模块
        self._build_video_import_module(left_panel)

        # 【模块2】对齐模式设置模块
        self._build_alignment_mode_module(left_panel)

        # 【模块3】生成/导出模块
        self._build_generation_module(left_panel)

        left_panel.addStretch()

        main_layout.addLayout(left_panel, stretch=1)

        # --- 右侧区域 ---
        right_panel = QVBoxLayout()

        self.preview_tab_widget = QTabWidget()
        self.preview_tab_widget.currentChanged.connect(self.on_display_tab_changed)

        # 预览 Tab
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QLabel("预览区域（由 VLC 渲染）")
        self.video_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setStyleSheet("background-color: black; color: gray;")
        self.video_widget.setMinimumHeight(300)
        preview_layout.addWidget(self.video_widget)
        self.preview_tab_widget.addTab(preview_tab, "预览")

        # 视频对比 Tab
        self.comparison_widget = VideoComparisonWidget(self.ref_paths, self.user_paths, self)
        self.preview_tab_widget.addTab(self.comparison_widget, "视频对比")

        right_panel.addWidget(self.preview_tab_widget, stretch=1)
        self._build_unified_playback_module(right_panel)

        main_layout.addLayout(right_panel, stretch=4)
        self.refresh_duration_display()
        self.update_unified_playback_ui()
    
    def _build_video_import_module(self, parent_layout):
        """【模块1】构建动作片段导入模块"""
        from PySide6.QtWidgets import QGroupBox
        
        group_box = QGroupBox("📁 动作片段导入")
        group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #4A90E2;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        
        module_layout = QVBoxLayout(group_box)
        
        # 参考动作区域
        module_layout.addWidget(QLabel("参考动作片段 (显示在左侧)"))
        self.ref_list_widget = QListWidget()
        self.ref_list_widget.setMaximumHeight(100)
        self.ref_list_widget.currentRowChanged.connect(lambda r: self.sync_combo_selection(r, is_ref=True))
        module_layout.addWidget(self.ref_list_widget)

        layout_ref_btns = QHBoxLayout()
        btn_import_ref = QPushButton("导入参考")
        btn_import_ref.clicked.connect(self.import_ref_video)
        btn_remove_ref = QPushButton("移除参考")
        btn_remove_ref.clicked.connect(self.remove_ref_video)
        layout_ref_btns.addWidget(btn_import_ref)
        layout_ref_btns.addWidget(btn_remove_ref)
        module_layout.addLayout(layout_ref_btns)

        module_layout.addSpacing(5)

        # 用户动作区域
        module_layout.addWidget(QLabel("用户动作片段 (显示在右侧)"))
        self.user_list_widget = QListWidget()
        self.user_list_widget.setMaximumHeight(100)
        self.user_list_widget.currentRowChanged.connect(lambda r: self.sync_combo_selection(r, is_ref=False))
        module_layout.addWidget(self.user_list_widget)

        layout_user_btns = QHBoxLayout()
        btn_import_user = QPushButton("导入用户")
        btn_import_user.clicked.connect(self.import_user_video)
        btn_remove_user = QPushButton("移除用户")
        btn_remove_user.clicked.connect(self.remove_user_video)
        layout_user_btns.addWidget(btn_import_user)
        layout_user_btns.addWidget(btn_remove_user)
        module_layout.addLayout(layout_user_btns)

        # 剪辑器入口按钮
        module_layout.addSpacing(10)
        btn_clip_editor = QPushButton("✂ 动作片段剪辑器")
        btn_clip_editor.clicked.connect(self.open_clip_editor)
        btn_clip_editor.setStyleSheet("""
            QPushButton {
                background-color: #FF6B6B;
                color: white;
                font-weight: bold;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #FF5252;
            }
        """)
        module_layout.addWidget(btn_clip_editor)
        
        parent_layout.addWidget(group_box)
    

    # -------------------------------------------------------------
    # 采用紧凑的水平布局
    # -------------------------------------------------------------
    def _build_alignment_mode_module(self, parent_layout):
        """【模块2】构建对齐模式模块 (紧凑布局版)"""
        from PySide6.QtWidgets import QGroupBox, QStackedWidget
        
        group_box = QGroupBox("⚙️ 对齐模式设置")
        group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #50C878;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        
        module_layout = QVBoxLayout(group_box)
        module_layout.setSpacing(5) # 减小垂直间距
        
        # --- 第一行：模式选择 (水平布局) ---
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(QLabel("选择模式:"))
        self.align_mode_combo = QComboBox()
        self.align_mode_combo.addItem("手动对齐模式")
        self.align_mode_combo.addItem("击球时刻对齐模式")
        self.align_mode_combo.currentIndexChanged.connect(self.on_align_mode_changed)
        row1_layout.addWidget(self.align_mode_combo, stretch=1)
        module_layout.addLayout(row1_layout)
        
        module_layout.addSpacing(5)
        
        # 使用 QStackedWidget 切换不同模式的界面
        self.align_mode_stack = QStackedWidget()
        
        # === 界面 A: 手动对齐模式 (紧凑化) ===
        manual_widget = QWidget()
        manual_layout = QVBoxLayout(manual_widget)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(5)
        
        # 视频选择行
        h_vid = QHBoxLayout()
        h_vid.addWidget(QLabel("目标视频:"))
        self.manual_video_combo = QComboBox()
        self.manual_video_combo.currentIndexChanged.connect(self.load_current_video_settings)
        h_vid.addWidget(self.manual_video_combo, stretch=1)
        manual_layout.addLayout(h_vid)
        
        # 截断设置行 (将去头和去尾放在同一行)
        h_trim = QHBoxLayout()
        
        h_trim.addWidget(QLabel("去头(帧):"))
        self.trim_start_input = QLineEdit("0")
        self.trim_start_input.setFixedWidth(60) # 固定宽度节省空间
        h_trim.addWidget(self.trim_start_input)
        
        h_trim.addSpacing(15) # 中间加点间距
        
        h_trim.addWidget(QLabel("去尾(帧):"))
        self.trim_end_input = QLineEdit("0")
        self.trim_end_input.setFixedWidth(60)
        h_trim.addWidget(self.trim_end_input)
        
        h_trim.addStretch() # 靠左对齐
        manual_layout.addLayout(h_trim)
        
        # 验证器与信号连接
        int_validator = QIntValidator(0, 999999, self)
        self.trim_start_input.setValidator(int_validator)
        self.trim_end_input.setValidator(int_validator)
        self.trim_start_input.textChanged.connect(self.save_current_video_settings)
        self.trim_end_input.textChanged.connect(self.save_current_video_settings)
        
        self.align_mode_stack.addWidget(manual_widget)
        
        # === 界面 B: 击球时刻对齐模式 (紧凑化) ===
        hit_widget = QWidget()
        hit_layout = QVBoxLayout(hit_widget)
        hit_layout.setContentsMargins(0, 0, 0, 0)
        hit_layout.setSpacing(5)
        
        # 视频选择行
        h_hit_vid = QHBoxLayout()
        h_hit_vid.addWidget(QLabel("目标视频:"))
        self.hit_video_combo = QComboBox()
        self.hit_video_combo.currentIndexChanged.connect(self.on_hit_video_selection_changed)
        h_hit_vid.addWidget(self.hit_video_combo, stretch=1)
        hit_layout.addLayout(h_hit_vid)
        
        # 操作行
        h_ctrl = QHBoxLayout()

        # 设置按钮
        self.btn_set_hit_moment = QPushButton("📍 设为击球点")
        self.btn_set_hit_moment.clicked.connect(self.set_hit_moment)
        self.btn_set_hit_moment.setStyleSheet("background-color: #FFD700; font-weight: bold; padding: 2px 5px;")
        h_ctrl.addWidget(self.btn_set_hit_moment)
        
        h_ctrl.addStretch()
        hit_layout.addLayout(h_ctrl)
        
        # 信息显示与应用行
        h_info = QHBoxLayout()
        
        self.hit_moment_label = QLabel("未设置")
        self.hit_moment_label.setStyleSheet("color: #E74C3C; font-weight: bold;")
        h_info.addWidget(self.hit_moment_label, stretch=1)
        
        self.btn_apply_hit_align = QPushButton("✓ 应用")
        self.btn_apply_hit_align.clicked.connect(self.apply_hit_moment_alignment)
        self.btn_apply_hit_align.setStyleSheet("background-color: #50C878; color: white; font-weight: bold; padding: 2px 10px;")
        h_info.addWidget(self.btn_apply_hit_align)
        
        hit_layout.addLayout(h_info)
        
        self.align_mode_stack.addWidget(hit_widget)
        
        # 添加到模块布局
        module_layout.addWidget(self.align_mode_stack)
        
        parent_layout.addWidget(group_box)
    
    def _build_generation_module(self, parent_layout):
        """【模块3】构建生成与导出模块。"""
        from PySide6.QtWidgets import QGroupBox
        
        group_box = QGroupBox("🎬 预览生成与导出")
        group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #9B59B6;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        
        module_layout = QVBoxLayout(group_box)
        
        self.loop_checkbox = QCheckBox("循环播放")
        module_layout.addWidget(self.loop_checkbox)

        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel("排版选择"))
        self.layout_mode_combo = QComboBox()
        self.layout_mode_combo.addItem("水平排版", "horizontal")
        self.layout_mode_combo.addItem("竖直排版", "vertical")
        self.layout_mode_combo.currentIndexChanged.connect(self.on_layout_mode_changed)
        layout_row.addWidget(self.layout_mode_combo, stretch=1)
        module_layout.addLayout(layout_row)
        
        btn_preview = QPushButton("▶ 生成并播放对比视频")
        btn_preview.clicked.connect(self.generate_preview)
        btn_preview.setStyleSheet("font-weight: bold; padding: 8px;")
        module_layout.addWidget(btn_preview)

        btn_export = QPushButton("💾 导出最终视频")
        btn_export.clicked.connect(self.export_final)
        btn_export.setStyleSheet("font-weight: bold; background-color: #3498DB; color: white; padding: 8px;")
        module_layout.addWidget(btn_export)

        self.progress = QProgressBar()
        module_layout.addWidget(self.progress)

        self.status_label = QLabel("状态：等待操作")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #2C3E50; font-size: 11px;")
        module_layout.addWidget(self.status_label)
        
        parent_layout.addWidget(group_box)

    def _build_unified_playback_module(self, parent_layout):
        """构建主界面统一播放控制模块。"""
        group_box = QGroupBox("▶ 统一播放控制")
        group_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #9B59B6;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        module_layout = QVBoxLayout(group_box)

        button_row = QHBoxLayout()
        self.unified_prev_button = QPushButton("◀ 上一帧")
        self.unified_prev_button.clicked.connect(self.on_unified_prev_frame)
        button_row.addWidget(self.unified_prev_button)

        self.unified_next_button = QPushButton("▶ 下一帧")
        self.unified_next_button.clicked.connect(self.on_unified_next_frame)
        button_row.addWidget(self.unified_next_button)

        self.unified_play_button = QPushButton("▶ 播放")
        self.unified_play_button.clicked.connect(self.on_unified_play_pause)
        self.unified_play_button.setStyleSheet("font-weight: bold;")
        button_row.addWidget(self.unified_play_button)

        button_row.addWidget(QLabel("速度:"))
        self.unified_speed_combo = QComboBox()
        self.unified_speed_combo.addItems(["0.1x", "0.25x", "0.5x", "1.0x"])
        self.unified_speed_combo.setCurrentText("1.0x")
        self.unified_speed_combo.currentTextChanged.connect(self.on_unified_speed_changed)
        button_row.addWidget(self.unified_speed_combo)
        button_row.addStretch()

        module_layout.addLayout(button_row)

        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("播放时长"))
        self.unified_duration_label = QLabel("--")
        self.unified_duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.unified_duration_label.setStyleSheet("color: #2C3E50; font-weight: bold;")
        duration_row.addWidget(self.unified_duration_label, stretch=1)
        module_layout.addLayout(duration_row)

        self.unified_progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.unified_progress_slider.setMinimum(0)
        self.unified_progress_slider.setMaximum(1000)
        self.unified_progress_slider.sliderPressed.connect(self.on_unified_slider_pressed)
        self.unified_progress_slider.sliderMoved.connect(self.on_unified_slider_moved)
        self.unified_progress_slider.sliderReleased.connect(self.on_unified_slider_released)
        module_layout.addWidget(self.unified_progress_slider)

        self.unified_info_label = QLabel("当前: 0 / 0    0.00s / 0.00s")
        self.unified_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unified_info_label.setStyleSheet("font-size: 12px; color: #2C3E50;")
        module_layout.addWidget(self.unified_info_label)

        parent_layout.addWidget(group_box)

    def close_active_clips(self):
        """显式关闭之前创建的 clips，释放 ffmpeg 句柄"""
        if self.active_clips:
            print("正在清理旧的视频资源...")
            for clip in self.active_clips:
                try:
                    clip.close()
                except Exception as e:
                    print(f"清理资源警告: {e}")
            self.active_clips = []

    # -------------------------------------------------------------
    # 辅助属性和替换旧的导入/移除逻辑
    # -------------------------------------------------------------
    @property
    def all_video_paths(self):
        """获取合并后的视频路径：先参考，后用户"""
        return self.ref_paths + self.user_paths

    def refresh_combo_box(self):
        """重新生成下拉框内容（同时更新手动对齐和击球对齐的下拉框）"""
        # 更新手动对齐模式的下拉框
        self.manual_video_combo.blockSignals(True)
        self.manual_video_combo.clear()
        
        # 更新击球对齐模式的下拉框
        self.hit_video_combo.blockSignals(True)
        self.hit_video_combo.clear()
        
        idx = 1
        for p in self.ref_paths:
            label = f"{idx}. [参考] {os.path.basename(p)}"
            self.manual_video_combo.addItem(label)
            self.hit_video_combo.addItem(label)
            idx += 1
        for p in self.user_paths:
            label = f"{idx}. [用户] {os.path.basename(p)}"
            self.manual_video_combo.addItem(label)
            self.hit_video_combo.addItem(label)
            idx += 1
            
        self.manual_video_combo.blockSignals(False)
        self.hit_video_combo.blockSignals(False)
        
        # 默认选中第一个
        if self.manual_video_combo.count() > 0:
            if self.manual_video_combo.currentIndex() < 0:
                self.manual_video_combo.setCurrentIndex(0)
        if self.hit_video_combo.count() > 0:
            if self.hit_video_combo.currentIndex() < 0:
                self.hit_video_combo.setCurrentIndex(0)

        if self.comparison_widget:
            self.comparison_widget.refresh_video_lists(self.ref_paths, self.user_paths)

    def reset_speed_duration_defaults(self):
        """将播放速度/时长恢复为基于原始视频的默认值。"""
        self.aligned_target_duration = None
        self.unified_speed_combo.blockSignals(True)
        self.unified_speed_combo.setCurrentText("1.0x")
        self.unified_speed_combo.blockSignals(False)
        self.refresh_duration_display()

    def get_source_duration_seconds(self):
        """获取当前自动时长计算的基准秒数。"""
        if self.current_align_mode == 1 and self.aligned_target_duration is not None:
            return self.aligned_target_duration
        if not self.all_video_paths:
            return 0.0
        return max(VideoFileClip(p).duration for p in self.all_video_paths)

    def get_output_duration_seconds(self):
        """根据当前速度计算最终输出时长。"""
        base_duration = self.get_source_duration_seconds()
        speed = self.get_unified_speed_value()
        if speed <= 0:
            return base_duration
        return base_duration / speed

    def refresh_duration_display(self):
        """刷新统一播放控制中的只读时长展示。"""
        if not hasattr(self, "unified_duration_label"):
            return
        duration = self.get_output_duration_seconds()
        self.unified_duration_label.setText(f"{duration:.2f} 秒" if duration > 0 else "--")

    def import_ref_video(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择参考视频", "", "Video (*.mp4 *.mov *.mkv *.avi)")
        if paths:
            for p in paths:
                # 打印视频时长和帧率
                try:
                    clip = VideoFileClip(p)
                    print(f"[参考] {os.path.basename(p)} 时长: {clip.duration:.3f}秒, 帧率: {clip.fps}")
                    clip.close()
                except Exception as e:
                    print(f"[参考] {os.path.basename(p)} 获取信息失败: {e}")

                self.ref_paths.append(p)
                self.ref_list_widget.addItem(p)
                self.video_settings[p] = {"trim_start": 0, "trim_end": 0}
            self.refresh_combo_box()
            self.reset_speed_duration_defaults()
            self.update_unified_playback_ui()

    def import_user_video(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择用户视频", "", "Video (*.mp4 *.mov *.mkv *.avi)")
        if paths:
            for p in paths:
                # 打印视频时长和帧率
                try:
                    clip = VideoFileClip(p)
                    print(f"[用户] {os.path.basename(p)} 时长: {clip.duration:.3f}秒, 帧率: {clip.fps}")
                    clip.close()
                except Exception as e:
                    print(f"[用户] {os.path.basename(p)} 获取信息失败: {e}")

                self.user_paths.append(p)
                self.user_list_widget.addItem(p)
                self.video_settings[p] = {"trim_start": 0, "trim_end": 0}
            self.refresh_combo_box()
            self.reset_speed_duration_defaults()
            self.update_unified_playback_ui()

    def remove_ref_video(self):
        row = self.ref_list_widget.currentRow()
        if row >= 0:
            p = self.ref_paths.pop(row)
            self.ref_list_widget.takeItem(row)
            if p in self.video_settings and p not in self.all_video_paths:
                del self.video_settings[p]
            self.refresh_combo_box()
            self.reset_speed_duration_defaults()
            self.update_unified_playback_ui()

    def remove_user_video(self):
        row = self.user_list_widget.currentRow()
        if row >= 0:
            p = self.user_paths.pop(row)
            self.user_list_widget.takeItem(row)
            if p in self.video_settings and p not in self.all_video_paths:
                del self.video_settings[p]
            self.refresh_combo_box()
            self.reset_speed_duration_defaults()
            self.update_unified_playback_ui()

    def sync_combo_selection(self, row, is_ref=True):
        """点击列表时，同步选中下拉框（同时更新两个下拉框）"""
        if row < 0: return
        
        # 计算在 Combo 中的全局索引
        if is_ref:
            global_idx = row
        else:
            global_idx = len(self.ref_paths) + row
            
        # 同步两个下拉框
        if global_idx < self.manual_video_combo.count():
            self.manual_video_combo.setCurrentIndex(global_idx)
        if global_idx < self.hit_video_combo.count():
            self.hit_video_combo.setCurrentIndex(global_idx)

    def current_display_mode(self):
        """返回当前右侧播放区域模式。"""
        return "comparison" if self.preview_tab_widget.currentIndex() == 1 else "preview"

    def on_layout_mode_changed(self, index):
        """统一处理排版模式切换。"""
        self.layout_mode = self.layout_mode_combo.currentData() or "horizontal"
        if self.comparison_widget:
            self.comparison_widget.set_layout_mode(self.layout_mode)

    def on_display_tab_changed(self, index):
        """切换显示 Tab 时刷新统一控制模块。"""
        if index == 1 and self.comparison_widget:
            self.comparison_widget.refresh_video_lists(self.ref_paths, self.user_paths)
        self.update_unified_playback_ui()

    def get_unified_speed_value(self):
        speed_map = {"0.1x": 0.1, "0.25x": 0.25, "0.5x": 0.5, "1.0x": 1.0}
        return speed_map.get(self.unified_speed_combo.currentText(), 0.25)

    def has_vlc_player(self):
        """统一判断 VLC 播放器是否已初始化。"""
        return hasattr(self, "vlc_player") and self.vlc_player is not None

    def has_unified_controls(self):
        """统一判断主界面播放控制控件是否已创建完成。"""
        return hasattr(self, "unified_progress_slider") and hasattr(self, "unified_info_label")

    def on_unified_prev_frame(self):
        if self.current_display_mode() == "comparison":
            if self.comparison_widget:
                self.comparison_widget.on_prev_frame()
        elif self.is_using_frame_player and self.frame_player:
            self.frame_player.prev_frame()
        elif not self.has_vlc_player():
            return
        else:
            self.seek_preview_by_offset(-1)
        self.update_unified_playback_ui()

    def on_unified_next_frame(self):
        if self.current_display_mode() == "comparison":
            if self.comparison_widget:
                self.comparison_widget.on_next_frame()
        elif self.is_using_frame_player and self.frame_player:
            self.frame_player.next_frame()
        elif not self.has_vlc_player():
            return
        else:
            self.seek_preview_by_offset(1)
        self.update_unified_playback_ui()

    def on_unified_play_pause(self):
        if self.current_display_mode() == "comparison":
            if not self.comparison_widget:
                return
            self.comparison_widget.playback_speed = self.get_unified_speed_value()
            self.comparison_widget.on_play_pause()
        elif self.is_using_frame_player and self.frame_player:
            if self.frame_player.is_playing:
                self.frame_player.pause()
            else:
                self.frame_player.play(self.get_unified_speed_value())
        elif not self.has_vlc_player():
            return
        else:
            self.stop_preview()
        self.update_unified_playback_ui()

    def on_unified_speed_changed(self, speed_text):
        speed = self.get_unified_speed_value()
        self.refresh_duration_display()
        if self.current_display_mode() == "comparison":
            if self.comparison_widget:
                self.comparison_widget.playback_speed = speed
            if self.comparison_widget and self.comparison_widget.is_playing:
                self.comparison_widget.stop_playback()
                self.comparison_widget.start_playback(speed)
        elif self.is_using_frame_player and self.frame_player and self.frame_player.is_playing:
            self.frame_player.play(speed)
        elif not self.has_vlc_player():
            return
        else:
            try:
                self.vlc_player.set_rate(speed)
            except Exception:
                pass
        self.update_unified_playback_ui()

    def on_unified_slider_pressed(self):
        if self.current_display_mode() == "comparison":
            if self.comparison_widget and self.comparison_widget.is_playing:
                self.comparison_widget.stop_playback()
        elif self.is_using_frame_player and self.frame_player and self.frame_player.is_playing:
            self.frame_player.pause()
        elif not self.has_vlc_player():
            return
        else:
            state = self.vlc_player.get_state()
            if state == vlc.State.Playing:
                self.vlc_player.pause()
        self.update_unified_playback_ui()

    def on_unified_slider_moved(self, value):
        if self.current_display_mode() == "comparison":
            if self.comparison_widget:
                self.comparison_widget.seek_active_player(value)
        elif self.is_using_frame_player and self.frame_player:
            self.frame_player.show_frame(value)
        elif not self.has_vlc_player():
            return
        else:
            self.seek_preview_to_ms(value)
        self.update_unified_playback_ui()

    def on_unified_slider_released(self):
        self.update_unified_playback_ui()

    def seek_preview_by_offset(self, direction):
        """按预估帧长前后移动预览视频。"""
        if not os.path.exists(self.preview_path):
            return
        fps = get_video_fps(self.preview_path)
        frame_ms = int(1000 / fps) if fps > 0 else 33
        current_time = max(0, self.vlc_player.get_time())
        self.seek_preview_to_ms(max(0, current_time + direction * frame_ms))

    def seek_preview_to_ms(self, target_ms):
        if target_ms < 0:
            target_ms = 0
        try:
            self.vlc_player.set_time(int(target_ms))
        except Exception:
            pass

    def update_unified_playback_ui(self):
        """根据当前 Tab 更新统一播放控制模块显示。"""
        if not self.has_unified_controls():
            return

        if self.current_display_mode() == "comparison":
            info = self.comparison_widget.get_active_media_info() if self.comparison_widget else None
            self.unified_prev_button.setEnabled(bool(info))
            self.unified_next_button.setEnabled(bool(info))
            self.unified_progress_slider.blockSignals(True)
            if info:
                total_frames = info['total_frames']
                frame_idx = info['frame_index']
                total_time = total_frames / info['fps'] if info['fps'] > 0 else 0
                self.unified_progress_slider.setMaximum(max(0, total_frames - 1))
                self.unified_progress_slider.setValue(frame_idx)
                self.unified_info_label.setText(
                    f"当前: {frame_idx} / {total_frames} 帧    {info['time_seconds']:.2f}s / {total_time:.2f}s"
                )
            else:
                self.unified_progress_slider.setMaximum(1000)
                self.unified_progress_slider.setValue(0)
                self.unified_info_label.setText("当前: 0 / 0 帧    0.00s / 0.00s")
            self.unified_progress_slider.blockSignals(False)
            self.unified_play_button.setText("⏸ 暂停" if self.comparison_widget and self.comparison_widget.is_playing else "▶ 播放")
            return

        if self.is_using_frame_player and self.frame_player:
            info = self.frame_player.get_current_frame_info()
            self.unified_progress_slider.blockSignals(True)
            if info:
                total_frames = info['total_frames']
                frame_idx = info['frame_index']
                total_time = total_frames / info['fps'] if info['fps'] > 0 else 0
                self.unified_progress_slider.setMaximum(max(0, total_frames - 1))
                self.unified_progress_slider.setValue(frame_idx)
                self.unified_info_label.setText(
                    f"当前: {frame_idx} / {total_frames} 帧    {info['time_seconds']:.2f}s / {total_time:.2f}s"
                )
            else:
                self.unified_progress_slider.setMaximum(1000)
                self.unified_progress_slider.setValue(0)
                self.unified_info_label.setText("当前: 0 / 0 帧    0.00s / 0.00s")
            self.unified_progress_slider.blockSignals(False)
            self.unified_prev_button.setEnabled(bool(info))
            self.unified_next_button.setEnabled(bool(info))
            self.unified_play_button.setText("⏸ 暂停" if self.frame_player.is_playing else "▶ 播放")
            return

        if not self.has_vlc_player():
            self.unified_progress_slider.blockSignals(True)
            self.unified_progress_slider.setMaximum(1000)
            self.unified_progress_slider.setValue(0)
            self.unified_progress_slider.blockSignals(False)
            self.unified_prev_button.setEnabled(False)
            self.unified_next_button.setEnabled(False)
            self.unified_info_label.setText("当前: 0.00s / 0.00s")
            self.unified_play_button.setText("▶ 播放")
            return

        current_time = max(0, self.vlc_player.get_time())
        total_time = max(0, self.vlc_player.get_length())
        self.unified_progress_slider.blockSignals(True)
        self.unified_progress_slider.setMaximum(max(1000, total_time))
        self.unified_progress_slider.setValue(min(current_time, self.unified_progress_slider.maximum()))
        self.unified_progress_slider.blockSignals(False)
        self.unified_prev_button.setEnabled(os.path.exists(self.preview_path))
        self.unified_next_button.setEnabled(os.path.exists(self.preview_path))
        self.unified_info_label.setText(
            f"当前: {current_time / 1000:.2f}s / {total_time / 1000:.2f}s"
            if total_time > 0 else "当前: 0.00s / 0.00s"
        )
        state = self.vlc_player.get_state()
        self.unified_play_button.setText("⏸ 暂停" if state == vlc.State.Playing else "▶ 播放")

    # -------------------------------------------------------------
    #   设置保存与加载逻辑
    # -------------------------------------------------------------
    def save_current_video_settings(self):
        """将当前输入框的值保存到对应视频的设置字典中"""
        idx = self.manual_video_combo.currentIndex()
        if idx < 0 or idx >= len(self.all_video_paths):
            return
        
        current_path = self.all_video_paths[idx]
        
        try:
            start_f = int(self.trim_start_input.text() or 0)
            end_f = int(self.trim_end_input.text() or 0)
        except ValueError:
            return

        if current_path in self.video_settings:
            self.video_settings[current_path]["trim_start"] = start_f
            self.video_settings[current_path]["trim_end"] = end_f

    def load_current_video_settings(self):
        """根据下拉框选中的视频，回显设置到输入框"""
        idx = self.manual_video_combo.currentIndex()

        # 反向同步列表选中状态的逻辑更新
        if idx >= 0:
            if idx < len(self.ref_paths):
                # 属于参考视频
                self.ref_list_widget.setCurrentRow(idx)
                self.user_list_widget.clearSelection()
            else:
                # 属于用户视频
                user_idx = idx - len(self.ref_paths)
                self.user_list_widget.setCurrentRow(user_idx)
                self.ref_list_widget.clearSelection()

        if idx < 0 or idx >= len(self.all_video_paths):
            # 如果没有选中任何视频，清空或禁用
            self.trim_start_input.blockSignals(True)
            self.trim_end_input.blockSignals(True)
            self.trim_start_input.setText("0")
            self.trim_end_input.setText("0")
            self.trim_start_input.blockSignals(False)
            self.trim_end_input.blockSignals(False)
            return
        
        current_path = self.all_video_paths[idx]
        settings = self.video_settings.get(current_path, {"trim_start": 0, "trim_end": 0})
        
        self.trim_start_input.blockSignals(True)
        self.trim_end_input.blockSignals(True)
        
        # 优先用帧数参数，没有则用时间参数换算为帧数
        trim_start = settings.get("trim_start")
        trim_end = settings.get("trim_end")
        if trim_start is None and "trim_start_time" in settings:
            # 用时间参数换算为帧数（向下取整）
            try:
                clip = VideoFileClip(current_path)
                fps = clip.fps if clip.fps else 24
                trim_start = int(settings.get("trim_start_time", 0) * fps)
                clip.close()
            except Exception:
                trim_start = 0
        if trim_end is None and "trim_end_time" in settings:
            try:
                clip = VideoFileClip(current_path)
                fps = clip.fps if clip.fps else 24
                trim_end = int(settings.get("trim_end_time", 0) * fps)
                clip.close()
            except Exception:
                trim_end = 0

        self.trim_start_input.setText(str(trim_start if trim_start is not None else 0))
        self.trim_end_input.setText(str(trim_end if trim_end is not None else 0))
        
        self.trim_start_input.blockSignals(False)
        self.trim_end_input.blockSignals(False)

        # 如果是击球对齐模式，更新击球时刻显示
        if self.current_align_mode == 1:
            self.update_hit_moment_display()

    # 使用StackedWidget切换界面 
    def on_align_mode_changed(self, index):
        """对齐模式切换时的处理"""
        self.current_align_mode = index
        
        # 切换到对应的界面
        self.align_mode_stack.setCurrentIndex(index)
        
        if index == 0:  # 手动对齐模式
            # 启用手动截断控件
            self.trim_start_input.setEnabled(True)
            self.trim_end_input.setEnabled(True)
        else:  # 击球时刻对齐模式
            # 更新击球时刻显示
            self.update_hit_moment_display()
        self.refresh_duration_display()
    
    def on_hit_video_selection_changed(self):
        """击球对齐模式下，视频选择改变时的处理"""
        self.update_hit_moment_display()
        if self.current_align_mode == 1:
            self.load_hit_video_for_marking()
        
    def update_hit_moment_display(self):
        """更新击球时刻显示信息"""
        idx = self.hit_video_combo.currentIndex()
        if idx < 0 or idx >= len(self.all_video_paths):
            self.hit_moment_label.setText("击球时刻: 未设置")
            return
        
        current_path = self.all_video_paths[idx]
        
        # 只显示击球时刻 
        if current_path in self.hit_moments:
            hit_info = self.hit_moments[current_path]
            # 简化显示格式以适应紧凑布局
            self.hit_moment_label.setText(
                f"已设: 第{hit_info['hit_frame']}帧 ({hit_info['hit_time']:.2f}s)"
            )
        else:
            self.hit_moment_label.setText("击球时刻: 未设置")

    def load_hit_video_for_marking(self):
        """将当前击球对齐目标视频加载到预览区，交由统一播放控制模块控制。"""
        idx = self.hit_video_combo.currentIndex()
        if idx < 0 or idx >= len(self.all_video_paths):
            return

        current_path = self.all_video_paths[idx]

        self.vlc_player.stop()
        self.is_using_frame_player = True

        total_frames, fps = self.frame_player.load_video(current_path)
        if total_frames is None:
            self.status_label.setText(f"无法加载视频: {os.path.basename(current_path)}")
            self.is_using_frame_player = False
            return

        self.preview_tab_widget.setCurrentIndex(0)
        self.status_label.setText(
            f"[击球对齐] 已加载: {os.path.basename(current_path)} | "
            f"总帧数: {total_frames} | FPS: {fps:.2f} | 请使用下方统一播放控制定位"
        )
        self.update_unified_playback_ui()
    
    def play_single_video_for_hit_moment(self):
        """播放单个视频以便设置击球时刻（使用精确帧播放器）"""
        self.load_hit_video_for_marking()
        if self.is_using_frame_player:
            self.frame_player.play(self.get_unified_speed_value())


    # 暂停方法支持帧播放器
    def pause_for_hit_moment(self):
        """暂停击球时刻设置时的视频播放"""
        if self.is_using_frame_player:
            # 使用帧播放器时
            self.frame_player.pause()
            frame_info = self.frame_player.get_current_frame_info()
            if frame_info:
                self.status_label.setText(
                    f"已暂停 | 当前: 第{frame_info['frame_index']}帧 "
                    f"({frame_info['time_seconds']:.3f}秒)"
                )
            else:
                self.status_label.setText("已暂停，可设置击球时刻")
        else:
            # 使用VLC时
            self.vlc_player.pause()
            state = self.vlc_player.get_state()
            if state == vlc.State.Paused:
                self.status_label.setText("已暂停，可设置击球时刻")
    
    def change_hit_playback_speed(self, speed_text):
        """改变击球时刻设置时的播放速度"""
        self.update_unified_playback_ui()
    
    # 逐帧控制方法
    def prev_frame_for_hit(self):
        """后退一帧"""
        if self.is_using_frame_player:
            self.frame_player.prev_frame()
            frame_info = self.frame_player.get_current_frame_info()
            if frame_info:
                self.status_label.setText(
                    f"当前: 第{frame_info['frame_index']}帧 "
                    f"({frame_info['time_seconds']:.3f}秒)"
                )
        else:
            self.status_label.setText("请先播放视频")
    
    def next_frame_for_hit(self):
        """前进一帧"""
        if self.is_using_frame_player:
            self.frame_player.next_frame()
            frame_info = self.frame_player.get_current_frame_info()
            if frame_info:
                self.status_label.setText(
                    f"当前: 第{frame_info['frame_index']}帧 "
                    f"({frame_info['time_seconds']:.3f}秒)"
                )
        else:
            self.status_label.setText("请先播放视频")

    def set_hit_moment(self):
        """设置当前视频的击球时刻（精确到帧）"""
        idx = self.hit_video_combo.currentIndex()
        if idx < 0 or idx >= len(self.all_video_paths):
            self.status_label.setText("请先选择一个视频")
            return
        
        current_path = self.all_video_paths[idx]
        
        if self.is_using_frame_player:
            # 使用帧播放器时，获取精确的帧信息
            frame_info = self.frame_player.get_current_frame_info()
            
            if frame_info:
                # 保存击球时刻信息
                self.hit_moments[current_path] = {
                    'hit_frame': frame_info['frame_index'],
                    'hit_time': frame_info['time_seconds'],
                    'fps': frame_info['fps']
                }
                
                self.update_hit_moment_display()
                self.status_label.setText(
                    f"✓ 击球时刻已设置: 第 {frame_info['frame_index']} 帧 "
                    f"({frame_info['time_seconds']:.3f}秒) [精确]"
                )
            else:
                self.status_label.setText("无法获取当前帧信息")
        else:
            # 使用VLC时的传统方法（精度较低）
            current_time = self.vlc_player.get_time() / 1000.0  # 转换为秒
            
            try:
                clip = VideoFileClip(current_path)
                fps = clip.fps if clip.fps else 24
                current_frame = int(current_time * fps)
                clip.close()
                
                self.hit_moments[current_path] = {
                    'hit_frame': current_frame,
                    'hit_time': current_time
                }
                
                self.update_hit_moment_display()
                self.status_label.setText(
                    f"已设置击球时刻: 第{current_frame}帧 ({current_time:.2f}秒) [VLC估算]"
                )
                
            except Exception as e:
                self.status_label.setText(f"设置击球时刻失败: {str(e)}")
    
    def apply_hit_moment_alignment(self):
        """应用击球时刻对齐，计算裁剪参数"""
        # 检查是否所有视频都设置了击球时刻
        missing_videos = []
        for path in self.all_video_paths:
            if path not in self.hit_moments:
                missing_videos.append(os.path.basename(path))
        
        if missing_videos:
            self.status_label.setText(f"以下视频未设置击球时刻: {', '.join(missing_videos)}")
            return
        
        # 修复击球对齐算法 
        try:
            # 1. 计算所有视频的击球前后可用时长
            video_infos = []
            for path in self.all_video_paths:
                hit_info = self.hit_moments[path]
                clip = VideoFileClip(path)
                fps = clip.fps if clip.fps else 24
                hit_frame = hit_info['hit_frame']
                hit_time = hit_info['hit_time']
                
                # 计算击球前后的最大可用时长
                before_available = hit_time  # 击球前的最大时长
                after_available = clip.duration - hit_time  # 击球后的最大时长
                
                # 计算比例：before / after
                ratio = before_available / after_available if after_available > 0 else 1.0
                
                video_infos.append({
                    'path': path,
                    'clip': clip,
                    'fps': fps,
                    'hit_frame': hit_frame,
                    'hit_time': hit_time,
                    'before_available': before_available,
                    'after_available': after_available,
                    'ratio': ratio
                })
                
                print(f"视频: {os.path.basename(path)}")
                print(f"  击球时刻: {hit_time:.3f}秒 (第{hit_frame}帧)")
                print(f"  before: {before_available:.3f}秒, after: {after_available:.3f}秒")
                print(f"  比例(before/after): {ratio:.3f}")
            
            # 2. 找到最大比例作为基准（保持原有逻辑不变）
            max_ratio = max(info['ratio'] for info in video_infos)
            print(f"\n基准比例(最大): {max_ratio:.3f}")
            
            # 3. 根据最大比例裁剪每个视频的末尾
            # 目标：使所有视频的 before/after 比例 = max_ratio
            # 方法：保持 before 不变，调整 after = before / max_ratio
            for info in video_infos:
                path = info['path']
                fps = info['fps']
                before_available = info['before_available']
                after_available = info['after_available']
                ratio = info['ratio']
                clip = info['clip']
                
                # 【关键计算】
                # 为了使比例 = max_ratio，需要的 after 时长
                required_after = before_available / max_ratio
                
                keep_until_time = info['hit_time'] + required_after  # 直接用时间
                
                self.video_settings[path] = {
                    'trim_start_time': 0,
                    'trim_end_time': clip.duration - keep_until_time  # 末尾需要裁掉的秒数
                }
                
                clip.close()
            
            # 4. 计算统一时长（基准视频的总时长）
            # 找到比例最大的视频（即基准视频）
            base_info = max(video_infos, key=lambda x: x['ratio'])
            # 统一时长 = 基准视频的 before + after
            unified_duration = base_info['before_available'] + base_info['after_available']
            self.aligned_target_duration = unified_duration
            self.refresh_duration_display()
            
            print(f"\n统一目标时长: {unified_duration:.3f}秒")
            print("=" * 60)
            
            self.status_label.setText(f"✓ 击球对齐完成 | 目标时长:{unified_duration:.2f}秒 | 比例:{max_ratio:.2f}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"击球对齐失败: {str(e)}")

    # -------------------------------------------------------------
    # 使用多线程生成预览视频
    # -------------------------------------------------------------
    def generate_preview(self):
        if not self.all_video_paths:
            self.status_label.setText("请先导入视频文件")
            return
        
        # ===== 宽高比一致性检测（严格模式） =====
        is_consistent, video_info = check_aspect_ratio_consistency(self.all_video_paths)
        
        if not is_consistent:
            # 构建详细的提示信息
            details_lines = []
            for info in video_info:
                details_lines.append(f"  • {info['name']}: {info['size']} (宽高比 {info['ratio']:.4f})")
            details = "\n".join(details_lines)
            
            QMessageBox.critical(
                self,
                "❌ 视频比例不一致",
                f"检测到以下视频的宽高比不一致（严格模式：误差>1%），无法生成对比视频。\n\n"
                f"📋 当前视频列表：\n{details}\n\n"
                f"💡 建议操作：\n"
                f"  1. 使用【✂ 动作片段剪辑器】统一裁剪为相同比例\n"
                f"  2. 或重新拍摄/导入相同方向的视频（全部横屏或全部竖屏）\n"
                f"  3. 确保所有视频都是16:9或都是9:16等统一比例\n\n"
                f"✅ 调整完成后，请重新导入视频并生成。"
            )
            self.status_label.setText("⚠ 操作已取消：视频宽高比不一致")
            return  # 阻止继续执行
        
        # 切换回VLC播放器
        # 如果正在使用帧播放器，切换回VLC模式
        if self.is_using_frame_player:
            self.frame_player.stop()
            self.is_using_frame_player = False
            # 清空帧播放器显示，恢复VLC提示文本
            self.video_widget.clear()
            self.video_widget.setText("预览区域（由 VLC 渲染）")
        
        # 停止现有线程（如果正在运行）
        if self.video_thread and self.video_thread.isRunning():
            self.status_label.setText("已有视频正在生成，请等待完成...")
            return
        
        # 在生成新视频前，先清理旧的资源，避免 WinError 6
        self.close_active_clips()
        
        self.save_current_video_settings()

        # 更新配置签名
        current_config = {
            "paths": list(self.all_video_paths),
            "ref_paths": list(self.ref_paths),  # 添加分组路径
            "user_paths": list(self.user_paths),
            "speed": self.get_unified_speed_value(),
            "duration": self.get_output_duration_seconds(),
            "settings": copy.deepcopy(self.video_settings),
            # 传入当前对齐模式
            "align_mode": self.current_align_mode,
            "layout_mode": self.layout_mode
        }

        if self.last_config == current_config and os.path.exists(self.preview_path):
            self.status_label.setText("直接播放上次生成的预览……")
            self.play_preview()
            return
        
        self.last_config = current_config
        self.status_label.setText("生成视频中，请稍候……")
        self.progress.setValue(0)

        self.vlc_player.stop()
        self.vlc_player.set_media(None)

        # 验证时长参数
        target_total_duration = self.get_output_duration_seconds()
        if target_total_duration <= 0.01:
            self.status_label.setText("错误：必须指定有效的播放时长（秒）")
            return

        # 创建并启动视频生成线程
        self.video_thread = VideoGeneratorThread(current_config, self.preview_path)
        
        # 连接信号到槽函数
        self.video_thread.progress_updated.connect(self.on_progress_updated)
        self.video_thread.status_updated.connect(self.on_status_updated)
        self.video_thread.finished_signal.connect(self.on_generation_finished)
        
        # 启动线程
        self.video_thread.start()
    
    # -------------------------------------------------------------
    # 线程信号处理槽函数
    # -------------------------------------------------------------
    def on_progress_updated(self, percent):
        """处理进度更新信号"""
        self.progress.setValue(percent)
    
    def on_status_updated(self, status):
        """处理状态更新信号"""
        self.status_label.setText(status)
    
    def on_generation_finished(self, success, message):
        """处理生成完成信号"""
        if success:
            self.progress.setValue(100)
            self.status_label.setText("预览生成完成，正在加载 VLC……")
            self.preview_tab_widget.setCurrentIndex(0)
            self.play_preview()
        else:
            self.status_label.setText(message)
            self.progress.setValue(0)

    # -------------------------------------------------------------
    #   使用 VLC 播放预览视频
    # -------------------------------------------------------------
    def play_preview(self):
        media = self.vlc_instance.media_new(self.preview_path)

        self.vlc_player.set_media(media)
        self.vlc_player.set_rate(self.get_unified_speed_value())
        self.vlc_player.play()

        # 重置手动停止标志，表示当前是正常播放
        self.is_manual_stop = False

        self.vlc_timer.start()
        if self.loop_checkbox.isChecked():
            self.status_label.setText("正在播放预览（循环播放）……")
        else:
            self.status_label.setText("正在播放预览……")

        # 播放开始时将焦点设置回主窗口，以便响应空格键
        self.setFocus()
        self.update_unified_playback_ui()

    def stop_preview(self):
        # 获取当前状态
        current_state = self.vlc_player.get_state()

        # 如果播放已结束、已停止或出错，则重新开始播放
        if current_state in [vlc.State.Ended, vlc.State.Stopped, vlc.State.Error]:
            if os.path.exists(self.preview_path):
                self.play_preview()
            return

        # 切换暂停/播放状态 (Toggle)
        # 这样点击"停止播放"时画面会冻结在当前帧，再次点击可继续播放
        self.vlc_player.pause()

        # 获取当前状态以更新 UI 和逻辑标志
        state = self.vlc_player.get_state()

        if state == vlc.State.Paused:
            self.is_manual_stop = True  # 标记为手动干预
            self.status_label.setText("播放已暂停")
            # 这里不再停止 vlc_timer，以便检测后续可能的状态变化（如用户再次点击恢复播放）
        elif state == vlc.State.Playing:
            # 恢复播放时显式重设速度，确保使用统一播放控制中的最新值。
            try:
                self.vlc_player.set_rate(self.get_unified_speed_value())
            except Exception:
                pass
            self.is_manual_stop = False # 恢复播放状态，允许循环逻辑生效
            self.status_label.setText("正在播放……")
            if not self.vlc_timer.isActive():
                self.vlc_timer.start()
        self.update_unified_playback_ui()

    def update_preview_status(self):
        state = self.vlc_player.get_state()

        # 只有在 结束(Ended)、停止(Stopped) 或 出错(Error) 时才视为真正结束
        if state in [vlc.State.Ended, vlc.State.Stopped, vlc.State.Error]:
            self.status_label.setText("播放结束")
            self.vlc_timer.stop()
        self.update_unified_playback_ui()

    def on_vlc_end(self, event):
        """
        VLC 线程回调：绝对不要在这里直接调用 self.vlc_player.stop/play 
        也不要操作 UI，否则会卡死或崩溃。
        这里只负责发射信号。
        """
        self.vlc_end_signal.emit()

    # 主线程槽函数
    def handle_vlc_end(self):
        """主线程槽函数：安全地处理播放结束逻辑"""
        # 如果是用户点的手动停止，则不做任何操作（不循环）
        if self.is_manual_stop:
            return

        if self.loop_checkbox.isChecked():
            # 循环模式：重新加载并播放
            # 先 stop 确保状态重置（对某些 VLC 版本很重要）
            self.vlc_player.stop()
            self.vlc_player.play()
            # 确保定时器继续运行以监控状态
            if not self.vlc_timer.isActive():
                self.vlc_timer.start()
            self.status_label.setText("正在循环播放……")
        else:
            self.vlc_timer.stop()
            self.status_label.setText("预览播放结束")
        self.update_unified_playback_ui()
    
    # 重写键盘事件处理，支持空格键暂停/继续
    def keyPressEvent(self, event):
        focus_widget = QApplication.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QComboBox, QListWidget)):
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Left:
            self.on_unified_prev_frame()
            event.accept()
            return

        if event.key() == Qt.Key.Key_Right:
            self.on_unified_next_frame()
            event.accept()
            return

        if event.key() == Qt.Key.Key_Space:
            self.on_unified_play_pause()
            event.accept()
            return

        super().keyPressEvent(event)

    def export_final(self):
        """导出最终对比视频：增加路径选择交互并修复未定义报错"""
        # 1. 前置检查：是否有视频
        if not self.all_video_paths:
            self.status_label.setText("请先导入视频文件")
            return
        
        # 2. 宽高比一致性检测（严格模式）
        is_consistent, video_info = check_aspect_ratio_consistency(self.all_video_paths)
        
        if not is_consistent:
            details_lines = []
            for info in video_info:
                details_lines.append(f"  • {info['name']}: {info['size']} (宽高比 {info['ratio']:.4f})")
            details = "\n".join(details_lines)
            
            QMessageBox.critical(
                self,
                "❌ 视频比例不一致",
                f"检测到以下视频的宽高比不一致（严格模式：误差>1%），无法导出最终视频。\n\n"
                f"📋 当前视频列表：\n{details}\n\n"
                f"💡 建议操作：\n"
                f"  1. 使用【✂ 动作片段剪辑器】统一裁剪为相同比例\n"
                f"  2. 或重新拍摄相同方向的视频（全部横屏或全部竖屏）\n\n"
                f"✅ 调整完成后，请重新导入视频并导出。"
            )
            self.status_label.setText("⚠ 操作已取消：视频宽高比不一致")
            return 

        # 3. 验证时长参数
        target_total_duration = self.get_output_duration_seconds()
        if target_total_duration <= 0.01:
            self.status_label.setText("错误：导出前必须指定有效的播放时长")
            return

        # 4. 检查是否有正在运行的线程
        if self.video_thread and self.video_thread.isRunning():
            self.status_label.setText("已有视频正在生成，请等待完成...")
            return

        # 5. 【核心修复】弹出保存对话框，锁定 save_path
        save_path, _ = QFileDialog.getSaveFileName(
            self, 
            "保存最终对比视频", 
            "comparison_output.mp4", 
            "MP4 Files (*.mp4)"
        )
        
        # 如果用户点击了取消，则退出流程
        if not save_path:
            self.status_label.setText("操作已取消：未选择保存路径")
            return

        # 6. 开始导出准备
        self.status_label.setText("正在导出最终视频……")
        self.progress.setValue(0)
        
        # 准备配置签名
        export_config = {
            "paths": list(self.all_video_paths),
            "ref_paths": list(self.ref_paths),
            "user_paths": list(self.user_paths),
            "speed": self.get_unified_speed_value(),
            "duration": target_total_duration,
            "settings": copy.deepcopy(self.video_settings),
            "align_mode": self.current_align_mode,
            "layout_mode": self.layout_mode
        }
        
        # 7. 创建并启动导出线程（传入已定义的 save_path）
        self.video_thread = ExportVideoThread(export_config, save_path)
        
        # 连接信号
        self.video_thread.progress_updated.connect(self.on_progress_updated)
        self.video_thread.status_updated.connect(self.on_status_updated)
        self.video_thread.finished_signal.connect(self.on_export_finished)
        
        # 启动线程
        self.video_thread.start()
    
    # -------------------------------------------------------------
    # 导出完成处理函数
    # -------------------------------------------------------------
    def on_export_finished(self, success, message):
        """处理导出完成信号"""
        if success:
            self.progress.setValue(100)
            self.status_label.setText("导出完成！")
        else:
            self.status_label.setText(message)
            self.progress.setValue(0)

    # 剪辑器相关方法
    def open_clip_editor(self):
        """打开剪辑器窗口"""
        editor = ClipEditorWindow(self)
        editor.exec()  # 模态对话框
    
    def import_clip_from_editor(self, clip_path, is_ref=False):
        """从剪辑器导入片段到主界面"""
        if not os.path.exists(clip_path):
            self.status_label.setText(f"文件不存在: {clip_path}")
            return
        
        try:
            # 验证视频有效性
            clip = VideoFileClip(clip_path)
            clip.close()
            
            # 导入到对应列表
            if is_ref:
                self.ref_paths.append(clip_path)
                self.ref_list_widget.addItem(clip_path)
            else:
                self.user_paths.append(clip_path)
                self.user_list_widget.addItem(clip_path)
            
            # 初始化设置
            self.video_settings[clip_path] = {"trim_start": 0, "trim_end": 0}
            
            # 刷新下拉框
            self.refresh_combo_box()
            
            self.status_label.setText(f"✓ 片段已导入: {os.path.basename(clip_path)}")
            
        except Exception as e:
            self.status_label.setText(f"导入片段失败: {str(e)}")

    def switch_to_comparison_mode(self):
        """兼容旧入口：切换到主界面中的视频对比 Tab。"""
        if not self.ref_paths and not self.user_paths:
            self.status_label.setText("请先导入视频文件")
            return
        self.preview_tab_widget.setCurrentIndex(1)
        self.on_display_tab_changed(1)
    
    def switch_to_main_mode(self):
        """兼容旧入口：切回主界面预览 Tab。"""
        self.preview_tab_widget.setCurrentIndex(0)
        self.on_display_tab_changed(0)

    # 添加资源清理
    def closeEvent(self, event):
        """窗口关闭时清理资源"""
        # 清理帧播放器
        if self.frame_player:
            self.frame_player.release()
        
        # 清理VLC播放器
        if self.vlc_player:
            self.vlc_player.stop()
        
        # 清理视频clips
        self.close_active_clips()
        
        event.accept()

# 如果您想直接运行这个文件进行测试，保留此代码块：
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
