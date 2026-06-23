from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'justina_gui'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        # Index de ament (NECESARIO para que ROS2 encuentre el paquete)
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),

        # package.xml
        ('share/' + package_name, ['package.xml']),

        # Recursos (gifs/png) instalados junto al paquete
        ('share/' + package_name, [
            'gui/abort.gif',
            'gui/microphone.png',
            'gui/JustinaScreen.png',
        ]),

        (
            os.path.join('share', package_name, 'launch'),
            glob('launch/*.xml'),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='vero',
    maintainer_email='veronica.morales.tepale@gmail.com',
    description='Justina GUI node',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # ros2 run gui gui_node
            'gui_node = gui.gui_node:main',
        ],
    },
)
