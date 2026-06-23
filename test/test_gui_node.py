from pathlib import Path
import sys
import types


def _stub_dependencies(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))

    rclpy = types.ModuleType('rclpy')
    rclpy.ok = lambda: True
    rclpy.init = lambda: None
    rclpy.shutdown = lambda: None
    rclpy.spin = lambda node: None
    monkeypatch.setitem(sys.modules, 'rclpy', rclpy)

    rclpy_node = types.ModuleType('rclpy.node')

    class Node:
        def __init__(self, *_args, **_kwargs):
            self.subscriptions = []

        def create_subscription(self, *args, **kwargs):
            self.subscriptions.append((args, kwargs))
            return object()

        def get_logger(self):
            return types.SimpleNamespace(error=lambda *_args, **_kwargs: None)

    rclpy_node.Node = Node
    monkeypatch.setitem(sys.modules, 'rclpy.node', rclpy_node)

    rclpy_qos = types.ModuleType('rclpy.qos')

    class QoSProfile:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class ReliabilityPolicy:
        RELIABLE = 'reliable'

    class HistoryPolicy:
        KEEP_LAST = 'keep_last'

    class DurabilityPolicy:
        VOLATILE = 'volatile'

    rclpy_qos.QoSProfile = QoSProfile
    rclpy_qos.ReliabilityPolicy = ReliabilityPolicy
    rclpy_qos.HistoryPolicy = HistoryPolicy
    rclpy_qos.DurabilityPolicy = DurabilityPolicy
    monkeypatch.setitem(sys.modules, 'rclpy.qos', rclpy_qos)

    sensor_msgs = types.ModuleType('sensor_msgs')
    sensor_msgs_msg = types.ModuleType('sensor_msgs.msg')

    class Image:
        pass

    sensor_msgs_msg.Image = Image
    monkeypatch.setitem(sys.modules, 'sensor_msgs', sensor_msgs)
    monkeypatch.setitem(sys.modules, 'sensor_msgs.msg', sensor_msgs_msg)

    std_msgs = types.ModuleType('std_msgs')
    std_msgs_msg = types.ModuleType('std_msgs.msg')

    class String:
        pass

    class Bool:
        pass

    std_msgs_msg.String = String
    std_msgs_msg.Bool = Bool
    monkeypatch.setitem(sys.modules, 'std_msgs', std_msgs)
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', std_msgs_msg)

    cv_bridge = types.ModuleType('cv_bridge')

    class CvBridge:
        def imgmsg_to_cv2(self, *args, **kwargs):
            return None

    cv_bridge.CvBridge = CvBridge
    monkeypatch.setitem(sys.modules, 'cv_bridge', cv_bridge)

    ament_index_python = types.ModuleType('ament_index_python')
    ament_index_python_packages = types.ModuleType('ament_index_python.packages')
    resource_dir = Path(__file__).resolve().parents[1] / 'resource' / 'justina_gui'
    ament_index_python_packages.get_package_share_directory = lambda name: str(resource_dir)
    monkeypatch.setitem(sys.modules, 'ament_index_python', ament_index_python)
    monkeypatch.setitem(
        sys.modules,
        'ament_index_python.packages',
        ament_index_python_packages,
    )

    cv2 = types.ModuleType('cv2')
    cv2.COLOR_BGR2RGB = 'bgr2rgb'
    cv2.INTER_AREA = 1
    cv2.cvtColor = lambda image, *_args, **_kwargs: image
    cv2.resize = lambda image, *_args, **_kwargs: image
    monkeypatch.setitem(sys.modules, 'cv2', cv2)

    pil_module = types.ModuleType('PIL')

    class DummyImage:
        def __init__(self, *args, **kwargs):
            self.size = (1, 1)

        def convert(self, *_args, **_kwargs):
            return self

        def resize(self, *_args, **_kwargs):
            return self

        def paste(self, *_args, **_kwargs):
            return None

        def crop(self, *_args, **_kwargs):
            return self

    class DummyImageTk:
        class PhotoImage:
            def __init__(self, *_args, **_kwargs):
                pass

    class DummyImageSequence:
        @staticmethod
        def Iterator(*_args, **_kwargs):
            return []

    pil_module.Image = DummyImage
    pil_module.ImageTk = DummyImageTk
    pil_module.ImageSequence = DummyImageSequence
    monkeypatch.setitem(sys.modules, 'PIL', pil_module)
    monkeypatch.setitem(sys.modules, 'PIL.Image', pil_module.Image)
    monkeypatch.setitem(sys.modules, 'PIL.ImageTk', pil_module.ImageTk)
    monkeypatch.setitem(sys.modules, 'PIL.ImageSequence', pil_module.ImageSequence)


def _import_gui_node(monkeypatch):
    _stub_dependencies(monkeypatch)
    sys.modules.pop('gui.gui_node', None)
    import gui.gui_node as gui_node

    return gui_node


def test_monitor_position_parses_xrandr(monkeypatch):
    gui_node = _import_gui_node(monkeypatch)
    monkeypatch.setattr(
        gui_node.subprocess,
        'check_output',
        lambda *args, **kwargs: 'HDMI-1 connected 1920x1080+0+0 60\n',
    )

    assert gui_node.monitor_position('HDMI-1') == (1920, 1080, 0, 0)


def test_detect_robot_monitor_prefers_1280x800(monkeypatch):
    gui_node = _import_gui_node(monkeypatch)
    monkeypatch.setattr(gui_node.shutil, 'which', lambda name: '/usr/bin/xrandr')
    monkeypatch.setattr(
        gui_node.subprocess,
        'check_output',
        lambda *args, **kwargs: (
            'HDMI-1 connected 1280x800+0+0 60\n'
            'DP-1 connected 1920x1080+0+0 60\n'
        ),
    )

    assert gui_node.detect_robot_monitor() == 'HDMI-1'


def test_talk_font_size_scales_down(monkeypatch):
    gui_node = _import_gui_node(monkeypatch)

    assert gui_node.talk_font_size('hola') == 75
    assert gui_node.talk_font_size('x' * 81) == 60
    assert gui_node.talk_font_size('x' * 141) == 50
    assert gui_node.talk_font_size('x' * 221) == 40
    assert gui_node.talk_font_size('x' * 301) == 35
