#! /usr/bin/env python3

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import tkinter as tk
from typing import Optional, Tuple

from ament_index_python.packages import get_package_share_directory
import cv2
from cv_bridge import CvBridge
from PIL import Image, ImageSequence, ImageTk
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image as RosImage
from std_msgs.msg import Bool, String


logger = logging.getLogger(__name__)

DEFAULT_SCREEN_SIZE = (1280, 800)
BACKGROUND_COLOR = '#111111'
ACCENT_COLOR = '#4DA3FF'
VISION_TITLE_HEIGHT = 60
ROS_IMAGE_DISPLAY_MS = 10000


def _resolve_resource_paths() -> Tuple[str, str, str]:
    try:
        pkg_dir = get_package_share_directory('justina_gui')
    except Exception as exc:
        pkg_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'resource', 'justina_gui')
        )
        logger.warning(
            'No se pudo resolver el paquete share de justina_gui: %s. Usando %s',
            exc,
            pkg_dir,
        )
    return (
        os.path.join(pkg_dir, 'JustinaScreen.png'),
        os.path.join(pkg_dir, 'abort.gif'),
        os.path.join(pkg_dir, 'microphone.png'),
    )


bioroboticsIMG, abortGif, microPNG = _resolve_resource_paths()


def monitor_position(monitor_name: str) -> Tuple[int, int, int, int]:
  
    xrandr_output = subprocess.check_output(['xrandr'], text=True, timeout=5)
    monitor_match = re.search(
        rf'^{re.escape(monitor_name)}\s+connected.*?(\d+)x(\d+)\+(\d+)\+(\d+)',
        xrandr_output,
        flags=re.MULTILINE,
    )
    if not monitor_match:
        raise RuntimeError(f"Monitor '{monitor_name}' no encontrado. Revisa `xrandr`.")
    width, height, pos_x, pos_y = map(int, monitor_match.groups())
    return width, height, pos_x, pos_y


def detect_robot_monitor() -> Optional[str]:
 
    if not shutil.which('xrandr'):
        logger.warning('xrandr no disponible en este entorno. Se usará monitor por defecto.')
        return None
    try:
        xrandr_output = subprocess.check_output(['xrandr'], text=True, timeout=5)
    except Exception as exc:
        logger.warning('No se pudo ejecutar xrandr: %s', exc)
        return None
    connected_monitors = [line for line in xrandr_output.splitlines() if ' connected' in line]
    for line in connected_monitors:
        if '1280x800' in line:
            return line.split()[0]
    for line in connected_monitors:
        name = line.split()[0]
        if name.startswith('DP-'):
            return name
    for line in connected_monitors:
        name = line.split()[0]
        if name.startswith('HDMI-'):
            return name
    return None


# ─── QoS profiles ────────────────────────────────────────────────────────────

def qos_reliable(depth: int = 1) -> QoSProfile:

    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        durability=DurabilityPolicy.VOLATILE,
    )


def qos_sensor(depth: int = 1) -> QoSProfile:

    return QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        durability=DurabilityPolicy.VOLATILE,
    )


class HSRBGui:
    def __init__(self, target_monitor: Optional[str] = None):
        self.root = tk.Tk()
        moved = False
        if target_monitor:
            try:
                w, h, x, y = monitor_position(target_monitor)
                self.root.geometry(f'{w}x{h}+{x}+{y}')
                moved = True
            except Exception as error:
                logger.warning("No se pudo mover GUI al monitor '%s': %s", target_monitor, error)
        if not moved:
            self.root.geometry('1280x800+0+0')

        self.root.overrideredirect(True)
        self.root.update_idletasks()
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=BACKGROUND_COLOR)
        self.root.lift()
        self.root.focus_force()
        self.screen_size = self._get_screen_size()

        self.image_label = tk.Label(
            self.root,
            bg=BACKGROUND_COLOR,
            borderwidth=0,
            highlightthickness=0,
        )
        self.footer_label = tk.Label(
            self.root, text='', font=('Arial', 24, 'bold'),
            borderwidth=0, bg=BACKGROUND_COLOR, fg='white',
        )
        self.text_talk = tk.Label(
            self.root, text='', font=('Arial', 75, 'bold'),
            wraplength=1150, justify='center', bg=BACKGROUND_COLOR, fg='white',
        )
        self.text_talkR = tk.Label(
            self.root, text='', font=('Helvetica', 45, 'bold'),
            bg=BACKGROUND_COLOR, fg=ACCENT_COLOR,
        )
        self.vision_title = tk.Label(
            self.root, text='', font=('Helvetica', 32, 'bold'),
            bg='#101010', fg=ACCENT_COLOR, pady=8,
        )

        self.frames = []
        self.frame_index = 0
        self.animating = False
        self.talk_timer = None
        self.ros_image_timer = None
        self.block_ros_debug = False
        self.gif_speed = 80
        self.is_closing = False
        self._ros_image_update_pending = False
        self._pending_ros_image = None

        self.root.protocol('WM_DELETE_WINDOW', self.request_close)

        # PRE-CACHE: procesar recursos pesados una sola vez al inicio
        self._idle_photo = self._prepare_idle_image()
        self._stop_frames = self._prepare_stop_frames()
        self._micro_photo = self._prepare_micro_image()

        self.show_idle()

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _get_screen_size(self) -> Tuple[int, int]:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if screen_w <= 0 or screen_h <= 0:
            return DEFAULT_SCREEN_SIZE
        return screen_w, screen_h

    def _prepare_idle_image(self) -> Optional[ImageTk.PhotoImage]:
        """Prepara la imagen idle en memoria al inicio. Se llama una sola vez."""
        try:
            screen_w, screen_h = self.screen_size
            original_img = Image.open(bioroboticsIMG).convert('RGB')
            original_w, original_h = original_img.size
            scale = min(screen_w / original_w, screen_h / original_h)
            new_w = int(original_w * scale)
            new_h = int(original_h * scale)
            resized_img = original_img.resize((new_w, new_h), Image.LANCZOS)
            final_img = Image.new('RGB', (screen_w, screen_h), BACKGROUND_COLOR)
            pos_x = (screen_w - new_w) // 2
            pos_y = (screen_h - new_h) // 2
            final_img.paste(resized_img, (pos_x, pos_y))
            return ImageTk.PhotoImage(final_img)
        except Exception as exc:
            logger.error('Error pre-cargando imagen idle: %s', exc)
            return None

    def _prepare_stop_frames(self):
        try:
            gif = Image.open(abortGif)
            return [
                ImageTk.PhotoImage(frame.convert('RGB'))
                for frame in ImageSequence.Iterator(gif)
            ]
        except Exception as exc:
            logger.error('Error pre-cargando STOP GIF: %s', exc)
            return []

    def _prepare_micro_image(self) -> Optional[ImageTk.PhotoImage]:
        try:
            img = Image.open(microPNG).convert('RGB')
            return ImageTk.PhotoImage(img)
        except Exception as exc:
            logger.error('Error pre-cargando MICRO IMG: %s', exc)
            return None

    def _cancel_timers(self):
        if self.talk_timer:
            try:
                self.root.after_cancel(self.talk_timer)
            except Exception:
                pass
            self.talk_timer = None
        if self.ros_image_timer:
            try:
                self.root.after_cancel(self.ros_image_timer)
            except Exception:
                pass
            self.ros_image_timer = None
        self.animating = False

    def _clear_layout(self):
        self.image_label.pack_forget()
        self.footer_label.pack_forget()
        self.text_talk.pack_forget()
        self.text_talkR.place_forget()
        self.vision_title.place_forget()

    # ─── Estados visuales ────────────────────────────────────────────────────

    def show_idle(self):
        self.block_ros_debug = False
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg=BACKGROUND_COLOR)
        self.image_label.config(bg=BACKGROUND_COLOR)
        self.image_label.pack(expand=True, fill='both')
        if self._idle_photo:
            self.image_label.config(image=self._idle_photo, text='', bg=BACKGROUND_COLOR)
        else:
            self.image_label.config(
                image='', text='Imagen no encontrada',
                font=('Arial', 30), bg=BACKGROUND_COLOR, fg='white',
            )

    def show_talk(self, text: str = 'Speaking...'):
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg=BACKGROUND_COLOR)
        self.text_talkR.config(
            text='JUSTINA SAYS', fg=ACCENT_COLOR,
            bg=BACKGROUND_COLOR, font=('Helvetica', 45, 'bold'),
        )
        self.text_talkR.place(relx=0.5, y=30, anchor='n')
        font_size = talk_font_size(text)
        self.text_talk.config(
            text=text, fg='white',
            bg=BACKGROUND_COLOR, font=('Arial', font_size, 'bold'),
        )
        screen_w, _ = self.screen_size
        wraplength = min(max(320, int(screen_w * 0.9)), 1150)
        self.text_talk.config(wraplength=wraplength)
        padx = max(24, int(screen_w * 0.06))
        self.text_talk.pack(expand=True, fill='both', padx=padx, pady=(100, 60))
        ms = int(max((len(text) / 8) * 1000, 2500))
        self.talk_timer = self.root.after(ms, self.show_idle)

    def show_stop(self):
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg=BACKGROUND_COLOR)
        self.image_label.config(
            bg=BACKGROUND_COLOR,
            borderwidth=0,
            highlightthickness=0,
        )
        self.image_label.pack(expand=True, fill='both')
        if not self._stop_frames:
            self.show_idle()
            return
        self.frames = self._stop_frames
        self.frame_index = 0
        self.animating = True
        self.gif_speed = 50
        self.animate()

    def show_micro(self):
        self.block_ros_debug = True
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg=BACKGROUND_COLOR)
        self.image_label.config(
            bg=BACKGROUND_COLOR,
            borderwidth=0,
            highlightthickness=0,
        )
        self.image_label.pack(expand=True, fill='both')
        if self._micro_photo:
            self.image_label.config(image=self._micro_photo, text='')
        else:
            self.show_idle()

    def animate(self):
        if not self.animating or not self.frames:
            return
        self.image_label.config(image=self.frames[self.frame_index])
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.root.after(self.gif_speed, self.animate)

    def show_ros_image(self, pil_image, title: str = 'VISION'):
        
        if self.block_ros_debug:
            return
        if self._ros_image_update_pending:
            self._pending_ros_image = (pil_image, title)
            return

        self._ros_image_update_pending = True
        self.animating = False
        self._cancel_timers()
        self._clear_layout()
        try:
            screen_w, screen_h = self.screen_size
            self.photo = ImageTk.PhotoImage(pil_image)
            self.image_label.config(image=self.photo, text='', bg=BACKGROUND_COLOR)
            self.image_label.pack(expand=True, fill='both')
            self.vision_title.config(text=title)
            self.vision_title.place(
                x=0,
                y=screen_h - VISION_TITLE_HEIGHT,
                width=screen_w,
            )
            self.root.update_idletasks()
            self.ros_image_timer = self.root.after(
                ROS_IMAGE_DISPLAY_MS,
                self.return_from_ros_image,
            )
        except Exception as exc:
            logger.error('Error mostrando imagen ROS: %s', exc)
        finally:
            self._ros_image_update_pending = False
            if self._pending_ros_image is not None:
                pending_image, pending_title = self._pending_ros_image
                self._pending_ros_image = None
                self.root.after(0, self.show_ros_image, pending_image, pending_title)

    def return_from_ros_image(self):
        self.ros_image_timer = None
        self.show_idle()

    # ─── Ciclo de vida ───────────────────────────────────────────────────────

    def run(self):
        def check_ros():
            if not rclpy.ok():
                self.request_close()
                return
            self.root.after(200, check_ros)
        check_ros()
        self.root.mainloop()

    def request_close(self):
        if self.is_closing:
            return
        self.is_closing = True
        self.root.after(0, self.close_gui)

    def close_gui(self):
        self._cancel_timers()
        self.animating = False
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def talk_font_size(text: str) -> int:
    length = len(text)
    if length > 300:
        return 35
    if length > 220:
        return 40
    if length > 140:
        return 50
    if length > 80:
        return 60
    return 75


class GuiNode(Node):
    def __init__(self, gui: HSRBGui):
        super().__init__('justina_gui_node')
        self.gui = gui
        self.current_state = None
        self.last_runstop = None
        self.bridge = CvBridge()
        self._image_lock = threading.Lock()
        self._image_processing = False
        self._pending_image = None

        # ─── Suscripciones ───────────────────────────────────────────────────
        self.create_subscription(
            Bool, '/navigation/navigation_ctrl/stop',
            self.runstop_callback, qos_reliable(depth=1),
        )
        self.create_subscription(
            String, '/hsrb/gui/state',
            self.state_callback, qos_reliable(depth=10),
        )
        self.create_subscription(
            String, '/hsrb/gui/text',
            self.text_callback, qos_reliable(depth=10),
        )
        self.create_subscription(
            RosImage, '/vision/owl/debug_image',
            self.debug_objects_callback, qos_sensor(),
        )
        self.create_subscription(
            RosImage, '/human_detection/pose_image_wrist',
            self.debug_waving_callback, qos_sensor(),
        )
        self.create_subscription(
            RosImage, '/face_recog/debug_image',
            self.debug_faces_callback, qos_sensor(),
        )
        self.create_subscription(
            RosImage, '/vision/detect_seats/debug_image',
            self.debug_seats_callback, qos_sensor(),
        )

    # ─── Callbacks ───────────────────────────────────────────────────────────

    def runstop_callback(self, msg: Bool):
        if self.last_runstop == msg.data:
            return
        self.last_runstop = msg.data
        self.gui.root.after(0, self.gui.show_stop if msg.data else self.gui.show_idle)

    def state_callback(self, msg: String):
        state = msg.data.lower().strip()
        if state == self.current_state:
            return
        self.current_state = state
        funcs = {
            'idle': self.gui.show_idle,
            'talk': lambda: self.gui.show_talk('Hablando...'),
            'stop': self.gui.show_stop,
            'micro': self.gui.show_micro,
        }
        if state in funcs:
            self.gui.root.after(0, funcs[state])

    def text_callback(self, msg: String):
        self.gui.root.after(0, self.gui.show_talk, msg.data)

    def _queue_debug_image(self, msg: RosImage, title: str):
        with self._image_lock:
            if self._image_processing:
                self._pending_image = (msg, title)
                return
            self._image_processing = True
        threading.Thread(
            target=self._process_image_queue,
            args=(msg, title),
            daemon=True,
        ).start()

    def _process_image_queue(self, msg: RosImage, title: str):
        while True:
            self._process_and_show(msg, title)
            with self._image_lock:
                if self._pending_image is None:
                    self._image_processing = False
                    return
                msg, title = self._pending_image
                self._pending_image = None

    def _process_and_show(self, msg: RosImage, title: str):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            img_h, img_w = cv_image.shape[:2]
            if img_w <= 0 or img_h <= 0:
                raise ValueError('Imagen ROS inválida')
            # BGR -> RGB fuera del hilo de Tkinter
            rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            screen_w, screen_h = self.gui.screen_size
            # Escalar con INTER_AREA (más rápido para downscale)
            scale = max(screen_w / img_w, screen_h / img_h)
            new_w = max(1, int(img_w * scale))
            new_h = max(1, int(img_h * scale))
            resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            # Recorte centrado
            if resized.shape[1] > screen_w:
                left = (resized.shape[1] - screen_w) // 2
                resized = resized[:, left:left + screen_w]
            if resized.shape[0] > screen_h:
                top = (resized.shape[0] - screen_h) // 2
                resized = resized[top:top + screen_h]
            pil_image = Image.fromarray(resized)
            # Solo la actualización visual va al hilo de Tkinter
            if not self.gui.is_closing:
                self.gui.root.after(0, self.gui.show_ros_image, pil_image, title)
        except Exception as exc:
            self.get_logger().error(f'Error procesando imagen [{title}]: {exc}')

    def debug_objects_callback(self, msg: RosImage):
        self._queue_debug_image(msg, 'OBJECT DETECTION')

    def debug_waving_callback(self, msg: RosImage):
        self._queue_debug_image(msg, 'WAVING DETECTION')

    def debug_faces_callback(self, msg: RosImage):
        self._queue_debug_image(msg, 'FACE DETECTION')

    def debug_seats_callback(self, msg: RosImage):
        self._queue_debug_image(msg, 'SEAT DETECTION')


def main():
    if not os.environ.get('DISPLAY'):
        os.environ['DISPLAY'] = ':0'
        logger.info('DISPLAY no definido, usando :0 por defecto')

    rclpy.init()
    target_monitor = detect_robot_monitor()
    logger.info('Monitor detectado para GUI: %s', target_monitor)
    gui = HSRBGui(target_monitor=target_monitor)
    node = GuiNode(gui)
    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    def handle_sigint(signum, frame):
        rclpy.shutdown()

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        gui.run()
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
