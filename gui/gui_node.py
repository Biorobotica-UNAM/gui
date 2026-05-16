#! /usr/bin/env python3

import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageSequence
import os
import re
import subprocess
import signal
import rclpy
import shutil
import cv2 
from sensor_msgs.msg import Image as RosImage
from cv_bridge import CvBridge
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from ament_index_python.packages import get_package_share_directory

pkg_dir = get_package_share_directory("justina_gui")

bioroboticsIMG = os.path.join(pkg_dir, "JustinaScreen.png")
abortGif = os.path.join(pkg_dir, "abort.gif")
pointingGif = os.path.join(pkg_dir, "pointing.gif")
microGif = os.path.join(pkg_dir, "microphone.gif")

def monitor_position(monitor_name: str):
    # Obtiene posición y tamaño de un monitor usando xrandr.
    xrandr_output = subprocess.check_output(["xrandr"], text=True)
    monitor_match = re.search(
        rf"^{re.escape(monitor_name)}\s+connected.*?(\d+)x(\d+)\+(\d+)\+(\d+)",
        xrandr_output,
        flags=re.MULTILINE
    )
    if not monitor_match:
        raise RuntimeError(f"Monitor '{monitor_name}' no encontrado. Revisa `xrandr`.")
    width, height, pos_x, pos_y = map(int, monitor_match.groups())
    return width, height, pos_x, pos_y

def detect_robot_monitor():
# Detecta monitor externo; None si no hay xrandr (1280x800 > DP > HDMI)
    if not shutil.which("xrandr"):
        print("[WARN] xrandr no disponible en este entorno. Se usará monitor por defecto.")
        return None
    try:
        xrandr_output = subprocess.check_output(["xrandr"], text=True, timeout=5)
    except Exception as e:
        print(f"[WARN] No se pudo ejecutar xrandr: {e}")
        return None
    connected_monitors = [
        line for line in xrandr_output.splitlines() if " connected" in line
    ]
    for line in connected_monitors:
        if "1280x800" in line:
            return line.split()[0]
    for line in connected_monitors:
        name = line.split()[0]
        if name.startswith("DP-"):
            return name
    for line in connected_monitors:
        name = line.split()[0]
        if name.startswith("HDMI-"):
            return name
    return None

class HSRBGui:
    def __init__(self, target_monitor=None):
        self.root = tk.Tk()
        # Intentar mover la GUI al monitor detectado
        moved = False
        if target_monitor:
            try:
                w, h, x, y = monitor_position(target_monitor)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
                moved = True
            except Exception as error:
                print(f"[WARN] No se pudo mover GUI al monitor '{target_monitor}': {error}")
        if not moved:
            # Fallback: ventana de tamaño estándar en posición 0,0
            self.root.geometry("1280x800+0+0")
        self.root.overrideredirect(True)
        self.root.update_idletasks()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111111")
        self.root.lift()
        self.root.focus_force()

        # Mostrar imagenes y GIFs 
        self.image_label = tk.Label(
            self.root,
            bg="#111111",
            borderwidth=0,
            highlightthickness=0
        )
        # Texto de pie de pagina 
        self.footer_label = tk.Label(
            self.root,
            text="",
            font=("Arial", 24, "bold"),
            borderwidth=0,
            bg="#111111",
            fg="white"
        )
        # Texto que dice el robot 
        self.text_talk = tk.Label(
            self.root,
            text="",
            font=("Arial", 75, "bold"),
            wraplength=1000,
            justify="center",
            bg="#111111",
            fg="white"
        )
        # Texto "ROBOT SAY" 
        self.text_talkR = tk.Label(
            self.root,
            text="",
            font=("Helvetica", 45, "bold"),
            bg="#111111",
            fg="#4DA3FF"
        )
        # Control de animacion 
        self.frames = []
        self.frame_index = 0
        self.animating = False
        self.talk_timer = None
        self.ros_image_timer = None
        self.block_ros_debug = False
        self.gif_speed = 80
        self.is_closing = False
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.show_idle()

    #FUNCION PARA DETENER CUALQUIER ANIMACION EN CURSO
    def _cancel_timers(self):
        if self.talk_timer:
            try:
                self.root.after_cancel(self.talk_timer)
            except Exception:
                pass
            self.talk_timer = None
        self.animating = False

    #FUNCION PARA EVITAR QUE SE ENCIMEN ELEMENTOS VISUALES  
    def _clear_layout(self):
        self.image_label.pack_forget()
        self.footer_label.pack_forget()
        self.text_talk.pack_forget()
        self.text_talkR.place_forget()

    #FUNCION PARA MOSTRAR LA PANTALLA DE REPOSO (idle)
    def show_idle(self):
        self.block_ros_debug = False
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg="#111111")
        self.image_label.config(bg="#111111")
        self.image_label.pack(expand=True, fill="both")
        try:
            screen_w, screen_h = 1280, 800
            original_img = Image.open(bioroboticsIMG).convert("RGB")
            original_w, original_h = original_img.size
            scale = min(screen_w / original_w, screen_h / original_h)
            new_w = int(original_w * scale)
            new_h = int(original_h * scale)
            resized_img = original_img.resize((new_w, new_h), Image.LANCZOS)
            final_img = Image.new("RGB", (screen_w, screen_h), "#111111")
            pos_x = (screen_w - new_w) // 2
            pos_y = (screen_h - new_h) // 2
            final_img.paste(resized_img, (pos_x, pos_y))
            self.photo = ImageTk.PhotoImage(final_img)
            self.image_label.config(image=self.photo, text="", bg="#111111")
        except Exception as e:
            print(f"Error en Idle: {e}")
            self.image_label.config(
                image="",
                text="Imagen no encontrada",
                font=("Arial", 30),
                bg="#111111",
                fg="white"
            )

    #FUNCION PARA MOSTRAR EN LA PANTALLA EL TEXTO QUE DICE EL ROBOT
    def show_talk(self, text="Speaking..."):
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg="#111111")

        #Encabezado de "ROBOT SAYS"
        self.text_talkR.config(
            text="ROBOT SAYS",
            fg="#4DA3FF",
            bg="#111111",
            font=("Helvetica", 45, "bold")
        )
        self.text_talkR.place(x=40, y=35)

        #Muestra el texto que dice el robot centrado en la pantalla
        self.text_talk.config(
            text=text,
            fg="white",
            bg="#111111",
            font=("Arial", 75, "bold")
        )
        #Timer para que se muestre el texto que dice Justina
        self.text_talk.pack(expand=True, fill="both", padx=70, pady=(120, 70))
        num_chars = len(text)
        ms = int(max((num_chars / 8) * 1000, 2500))
        self.talk_timer = self.root.after(ms, self.show_idle)

    #FUNCION DE CONFIGURACION DE LOS GIFs (TEXTO,COLOR DE TEXTO, TAMAÑO DEL GIF)
    def _setup_gif(self, gif_path, footer_text, speed=80, fullscreen=False):
        self._cancel_timers()
        self._clear_layout()
        self.gif_speed = speed
        bg_color = "#111111"
        footer_fg = "white"
        footer_text_upper = footer_text.upper()
        if "STOP" in footer_text_upper:
            footer_fg = "#FF4D4D"
        elif "POINT" in footer_text_upper:
            footer_fg = "#FFFFFF"
        elif "SPEAK" in footer_text_upper:
            footer_fg = "#FFFFFF"
        self.root.configure(bg=bg_color)
        self.footer_label.config(
            text=footer_text,
            bg=bg_color,
            fg=footer_fg,
            font=("Arial", 50, "bold")
        )
        self.footer_label.pack(side="bottom", fill="x", ipady=12)
        self.image_label.config(bg=bg_color)
        self.image_label.pack(side="top", expand=True, fill="both")
        try:
            gif = Image.open(gif_path)
            self.root.update_idletasks()
            
            # Calcula el area disponible para el GIF
            screen_w = 1280
            screen_h = 800 - self.footer_label.winfo_height()
            self.frames = []
            for frame in ImageSequence.Iterator(gif):
                frame = frame.convert("RGB")
                # GIF fullscreen optimizado
                if fullscreen:
                    self.frames.append(ImageTk.PhotoImage(frame))
                # GIF normal -> resize dinamico
                else:
                    original_w, original_h = frame.size
                    scale = min((screen_w * 0.95) / original_w, (screen_h * 0.95) / original_h)
                    new_w = int(original_w * scale)
                    new_h = int(original_h * scale)
                    resized_frame = frame.resize((new_w, new_h), Image.LANCZOS)
                    final_frame = Image.new("RGB", (screen_w, screen_h), bg_color)
                    pos_x = (screen_w - new_w) // 2
                    pos_y = (screen_h - new_h) // 2
                    final_frame.paste(resized_frame, (pos_x, pos_y))
                    self.frames.append(ImageTk.PhotoImage(final_frame))
            self.frame_index = 0
            self.animating = True
            self.animate()
        except Exception as e:
            print(f"Error GIF: {e}")
            self.show_idle()

    #FUNCION PARA MOSTRAR EL GIF DE PARO CUANDO SE ACTIVA EL BOTON DE EMERGENCIA
    def show_stop(self):
        self._setup_gif(abortGif, "STOP ACTIVATED", speed=50, fullscreen=True)

    #FUNCION PARA MOSTRAR EL GIF DE SEÑALAMIENTO
    def show_pointing(self):
        self._setup_gif(pointingGif, "POINT TO THE BAG", speed=200)

    #FUNCION PARA MOSTRAR EL GIF DE MICROFONO (CUANDO SE ESPERA RESPUESTA)
    def show_micro(self):
        self.block_ros_debug = True
        self._setup_gif(microGif, "SPEAK LOUDLY", speed=80, fullscreen=True)

    #FUNCION PARA MOSTRAR LAS ANIMACIOINES
    def animate(self):
        if not self.animating or not self.frames:
            return
        self.image_label.config(image=self.frames[self.frame_index])
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.root.after(self.gif_speed, self.animate)

    def run(self):
        def check_ros():
            if not rclpy.ok():
                self. request_close()
                return 
            self.root.after(200, check_ros)
        check_ros()
        self.root.mainloop()

    #FUNCION PARA EVITAR QUE SE INTENTE CERRAR DOS VECES
    def request_close(self):
        if self.is_closing:
            return
        self.is_closing = True
        self.root.after(0, self.close_gui)

    #FUNCION PARA CERRAR TKINTER
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

    # FUNCION PARA MOSTRAR IMAGENES DE ROS        
    def show_ros_image(self, cv_image):
        if self.block_ros_debug:
            return
        self.animating = False
        self._clear_layout()
        try:
            # OpenCV BGR -> RGB
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            # Convertir a PIL
            pil_image = Image.fromarray(cv_image)
            # DImensionar a la pantalla de JUstina
            screen_w = 1280
            screen_h = 800
            pil_image.thumbnail((screen_w, screen_h))
            final_img = Image.new("RGB", (screen_w, screen_h), "#111111")
            pos_x = (screen_w - pil_image.width) // 2
            pos_y = (screen_h - pil_image.height) // 2
            final_img.paste(pil_image, (pos_x, pos_y))
            self.photo = ImageTk.PhotoImage(final_img)
            self.image_label.config(image=self.photo, bg="#111111")
            self.image_label.pack(expand=True, fill="both")
            self.root.update_idletasks()
            # Reinicia timer cada vez que llega imagen nueva
            if self.ros_image_timer:
                try:
                    self.root.after_cancel(self.ros_image_timer)
                except Exception:
                    pass
            # Volver a idle si dejan de llegar imágenes
            self.ros_image_timer = self.root.after(30000, self.return_from_ros_image)
        except Exception as e:
            print(f"Error mostrando imagen ROS: {e}")

    def return_from_ros_image(self):
        self.ros_image_timer = None
        self.show_idle()

class GuiNode(Node):
    def __init__(self, gui: HSRBGui):
        super().__init__("justina_gui_node") 
        self.gui = gui
        self.current_state = None
        self.last_runstop = None
        self.bridge = CvBridge()
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.VOLATILE
        )
                                    # -------- Suscripciones ---------
        # STOP BUTTON 
        self.create_subscription(Bool, "/navigation/navigation_ctrl/stop", self.runstop_callback, qos)
        # JUSTINA STATES
        self.create_subscription(String, "/hsrb/gui/state", self.state_callback, 10)
        # TALKER TEXT
        self.create_subscription(String, "/hsrb/gui/text", self.text_callback, 10)
        # DEGUG_OBJECTS 
        self.create_subscription(RosImage, "/vision/owl/debug_image", self.debug_objects_callback, 10)
        # DEBUG_WAVING
        self.create_subscription(RosImage, "/human_detection/pose_image_wrist", self.debug_waving_callback, 10)
        # DEBUG_FACES
        self.create_subscription(RosImage, "/face_recog/debug_image", self.debug_faces_callback, 10)

                                    # -------- Callbacks ---------
    #FUNCION DE CALLBACK STOP BUTTON                                
    def runstop_callback(self, msg: Bool):
        if self.last_runstop == msg.data:
            return
        self.last_runstop = msg.data
        self.gui.root.after(0, self.gui.show_stop if msg.data else self.gui.show_idle)
    #FUNCION DE CALLBACK JUSTINA STATES (GIFs)
    def state_callback(self, msg: String):
        state = msg.data.lower().strip()
        if state == self.current_state:
            return
        self.current_state = state
        funcs = {
            "idle": self.gui.show_idle,
            "talk": lambda: self.gui.show_talk("Hablando..."),
            "pointing": self.gui.show_pointing,
            "stop": self.gui.show_stop,
            "micro": self.gui.show_micro
        }
        if state in funcs:
            self.gui.root.after(0, funcs[state])
    #FUNCION DE TALKER TEXT
    def text_callback(self, msg: String):
        self.gui.root.after(0, self.gui.show_talk, msg.data)
    #FUNCION DE CALLBACK DEBUG_OBJECTS
    def debug_objects_callback(self, msg: RosImage):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            self.gui.root.after(0, self.gui.show_ros_image, cv_image)
        except Exception as e:
            self.get_logger().error(f"Error debug_objects_callback: {e}")
    #FUNCION DE CALLBACK DEBUG_WAVING
    def debug_waving_callback(self, msg: RosImage):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            self.gui.root.after(0, self.gui.show_ros_image, cv_image)
        except Exception as e:
            self.get_logger().error(f"Error debug_waving_callback: {e}")
    # FUNCION DE CALLBACK DEBUG_FACES
    def debug_faces_callback(self, msg: RosImage):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            self.gui.root.after(0, self.gui.show_ros_image, cv_image)
        except Exception as e:
            self.get_logger().error(f"Error debug_faces_callback: {e}")

def main():
    # Si no hay DISPLAY definido usar :0 por defecto
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
        print("[INFO] DISPLAY no definido, usando :0 por defecto")

    rclpy.init()
    target_monitor = detect_robot_monitor()
    print(f"[INFO] Monitor detectado para GUI: {target_monitor}")
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

if __name__ == "__main__":
    main()   