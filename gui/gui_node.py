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
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rclpy.node import Node
from std_msgs.msg import String, Bool
 
baeDIR = os.path.dirname(os.path.abspath(__file__))
bioroboticsIMG = os.path.join(baeDIR, "JustinaScreen.png")
abortGif = os.path.join(baeDIR, "abort.gif")
pointingGif = os.path.join(baeDIR, "pointing.gif")
microGif = os.path.join(baeDIR, "microphone.gif")

def monitor_position(monitor_name: str):
    """Obtiene posición y tamaño de un monitor usando xrandr."""
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
        self.gif_speed = 80
        self.is_closing = False

        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.show_idle()

    # Detiene cualquier animacion en curso
    def _cancel_timers(self):
        if self.talk_timer:
            try:
                self.root.after_cancel(self.talk_timer)
            except Exception:
                pass
            self.talk_timer = None
        self.animating = False

    # Para evitar que se encimen elementos visuales 
    def _clear_layout(self):
        self.image_label.pack_forget()
        self.footer_label.pack_forget()
        self.text_talk.pack_forget()
        self.text_talkR.place_forget()

    # Muestra la pantalla de reposo (idle)
    def show_idle(self):
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

    # Muestra en la pantalla el texto que el robot esta diciendo
    def show_talk(self, text="Speaking..."):
        self._cancel_timers()
        self._clear_layout()
        self.root.configure(bg="#111111")

        # Muestra el encabezado de "ROBOT SAYS"
        self.text_talkR.config(
            text="ROBOT SAYS",
            fg="#4DA3FF",
            bg="#111111",
            font=("Helvetica", 45, "bold")
        )
        self.text_talkR.place(x=40, y=35)

        # Muestra el texto que dice el robot centrado en la pantalla
        self.text_talk.config(
            text=text,
            fg="white",
            bg="#111111",
            font=("Arial", 75, "bold")
        )
        # Timer para que se muestre el texto que dice Justina
        self.text_talk.pack(expand=True, fill="both", padx=70, pady=(120, 70))
        num_chars = len(text)
        ms = int(max((num_chars / 8) * 1000, 2500))
        self.talk_timer = self.root.after(ms, self.show_idle)

    def _setup_gif(self, gif_path, footer_text, speed=80):
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

    def show_stop(self):
        # Muestra el gif stop cuando se activa el boton de emergencia
        self._setup_gif(abortGif, "STOP ACTIVATED", speed=50)

    def show_pointing(self):
        # Muestra el gif de señalar
        self._setup_gif(pointingGif, "POINT TO THE BAG", speed=200)

    def show_micro(self):
        # Muestra el gif de microfono cuando el robot esta esperando respuesta
        self._setup_gif(microGif, "SPEAK LOUDLY", speed=80)

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

    # Evitar que se intente cerrar dos veces
    def request_close(self):
        if self.is_closing:
            return
        self.is_closing = True
        self.root.after(0, self.close_gui)

    # Cierra Tkinter
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

class GuiNode(Node):
    def __init__(self, gui: HSRBGui):
        super().__init__("hsrb_gui_node") 
        self.gui = gui
        self.current_state = None
        self.last_runstop = None
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.VOLATILE
        )
        self.create_subscription(Bool, "/runstop_button", self.runstop_callback, qos)
        self.create_subscription(String, "/hsrb/gui/state", self.state_callback, 10)
        self.create_subscription(String, "/hsrb/gui/text", self.text_callback, 10)

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
            "idle": self.gui.show_idle,
            "talk": lambda: self.gui.show_talk("Hablando..."),
            "pointing": self.gui.show_pointing,
            "stop": self.gui.show_stop,
            "micro": self.gui.show_micro
        }
        if state in funcs:
            self.gui.root.after(0, funcs[state])

    def text_callback(self, msg: String):
        self.gui.root.after(0, self.gui.show_talk, msg.data)

def main():
    # Si no hay DISPLAY definido usar :0 por defecto
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":1"
        print("[INFO] DISPLAY no definido, usando :1 por defecto")

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