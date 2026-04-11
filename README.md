# GUI de Justina

## Descripción general

La **GUI** es una interfaz gráfica desarrollada para ejecutarse en la pantalla frontal del robot, con el objetivo de mejorar la comunicación visual durante la interacción humano-robot.

Esta interfaz permite mostrar el **estado actual del robot**, instrucciones visuales para el usuario y el **texto de lo que el robot está diciendo** durante la ejecución de tareas.

La GUI está implementada en **Python utilizando Tkinter** y está integrada con **ROS2**, lo que permite que la interfaz responda dinámicamente a los mensajes publicados en distintos tópicos del sistema.

La interfaz está optimizada para la pantalla del robot.

---

# Funcionalidades principales

## Pantalla de reposo (Idle)

Cuando el robot no está interactuando con el usuario, la GUI muestra una pantalla de reposo con una imagen centrada.

Características:

- Pantalla completa
- Imagen centrada
- Adaptación automática a resolución **1280 × 800 - Justina**

---

## Visualización del habla del robot

Cuando el robot habla, la GUI muestra en pantalla el texto correspondiente al mensaje que el robot está diciendo.

Ejemplo:

ROBOT SAYS

Hello human, please place the bag here

Esto permite que el usuario comprenda al robot incluso en ambientes ruidosos.

---

## Instrucciones visuales para el usuario

La interfaz también muestra **animaciones GIF** que indican al usuario qué acción debe realizar.

Estados visuales implementados:

| Estado | Descripción |
|------|------|
| STOP | Indica que el botón de paro de seguridad fue activado |
| POINT TO THE BAG | Indica al usuario que señale la bolsa |
| SPEAK LOUDLY | Indica al usuario que hable más fuerte |
| IDLE | Pantalla de reposo |

Estas señales visuales ayudan a mejorar la **interacción humano-robot**.

---

# Integración con ROS2

La GUI se ejecuta como un **nodo de ROS2**, el cual escucha distintos tópicos para actualizar el estado de la interfaz.
