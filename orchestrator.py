import os
import time
from datetime import datetime
import cv2
import numpy as np
import yaml

from cobot_controller import FairinoController
from lights import LightsController
from camera import CameraCapture


# =====================================================================
# 1. OBSERVER PATTERN: EventBus for Real-Time Backend Feedback
# =====================================================================
class EventBus:
    """Publishes structured backend events to all subscribed listeners (UI, CLI, Supervisor)."""

    def __init__(self):
        self._listeners = []

    def subscribe(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)

    def emit(self, event_type, message="", **payload):
        event = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "type": event_type,
            "message": message,
            **payload,
        }
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass


# =====================================================================
# 2. STATE MACHINE PATTERN: Explicit Station Lifecycle States
# =====================================================================
class StationState:
    IDLE = "idle"
    PRECHECK = "precheck"
    CONNECTING = "connecting"
    MOVING_SAFE = "moving_safe"
    CAPTURING = "capturing"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


# =====================================================================
# 3. STRATEGY PATTERN: Interchangeable Real vs. Simulated Drivers
# =====================================================================
def generate_simulated_capture(output_dir, object_name, position_name, settings):
    """Create a synthetic inspection image when running in simulation mode (no joint numbers on screen)."""
    os.makedirs(output_dir, exist_ok=True)
    height, width = 720, 1080
    image = np.zeros((height, width, 3), dtype=np.uint8)

    image[:] = (28, 32, 38)
    for x in range(0, width, 60):
        cv2.line(image, (x, 0), (x, height), (42, 48, 56), 1)
    for y in range(0, height, 60):
        cv2.line(image, (0, y), (width, y), (42, 48, 56), 1)

    center = (width // 2, height // 2)
    cv2.circle(image, center, 170, (90, 175, 245), 3)
    cv2.circle(image, center, 85, (120, 220, 140), 2)
    cv2.line(image, (center[0] - 210, center[1]), (center[0] + 210, center[1]), (80, 130, 180), 1)
    cv2.line(image, (center[0], center[1] - 210), (center[0], center[1] + 210), (80, 130, 180), 1)

    timestamp_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    label = settings.get("label", position_name)

    lines = [
        f"INSPECTION CAPTURE - {object_name.upper()}",
        f"Station: {label}",
        f"Timestamp: {timestamp_display}",
    ]

    y_pos = 52
    for idx, text in enumerate(lines):
        color = (100, 230, 255) if idx == 0 else (225, 230, 235)
        scale = 0.85 if idx == 0 else 0.65
        thickness = 2 if idx == 0 else 1
        cv2.putText(
            image,
            text,
            (40, y_pos),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
        y_pos += 38

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{position_name}_{timestamp}.jpg"
    path = os.path.join(output_dir, filename)
    if not cv2.imwrite(path, image):
        raise RuntimeError(f"Failed to save simulated image: {path}")
    return path


class RealHardwareStrategy:
    """Executes station operations on physical Fairino Cobot, Modbus Relay, and Hikrobot Camera."""

    def __init__(self, config, robot_overrides=None):
        robot_cfg = dict(config.get("robot", {}))
        if robot_overrides:
            robot_cfg.update({k: v for k, v in robot_overrides.items() if v is not None})

        self.cobot = FairinoController(robot_cfg)
        self.lights = LightsController(config["relay"])
        self.camera = CameraCapture(config["camera"])
        self.lighting_delay = float(config.get("camera", {}).get("lighting_delay_sec", 0.5))
        self.active_lights = None

    def connect_all(self, bus=None):
        if bus:
            bus.emit("CONNECTION", "Connecting to Fairino Cobot...", device="cobot", status="CONNECTING")
        self.cobot.connect()
        if bus:
            bus.emit("CONNECTION", "Fairino Cobot connected", device="cobot", status="CONNECTED")

        if bus:
            bus.emit("CONNECTION", "Connecting to Relay Lights...", device="relay", status="CONNECTING")
        self.lights.connect()
        if bus:
            bus.emit("CONNECTION", "Relay Lights connected", device="relay", status="CONNECTED")

        if bus:
            bus.emit("CONNECTION", "Opening Hikrobot Camera...", device="camera", status="CONNECTING")
        self.camera.open()
        if bus:
            bus.emit("CONNECTION", "Hikrobot Camera connected", device="camera", status="CONNECTED")

    def move_to_step(self, position_name, settings, stop_event=None):
        if self.active_lights:
            self.lights.lights_off(self.active_lights)
            self.active_lights = None
        self.cobot.move_to_position_config(position_name, settings, stop_event=stop_event)

    def capture_at_step(self, object_name, position_name, settings):
        selected_lights = settings.get("lights") or []
        exposure_us = float(settings.get("exposure_time_us", 10000))
        if selected_lights:
            self.lights.lights_on(selected_lights)
            self.active_lights = selected_lights
        time.sleep(self.lighting_delay)
        return self.camera.capture(position_name=position_name, exposure_time_us=exposure_us)

    def emergency_stop(self):
        try:
            self.cobot.stop_motion()
        except Exception:
            pass

    def close_all(self):
        try:
            self.lights.all_enabled_off()
        except Exception:
            pass
        try:
            self.camera.close()
        except Exception:
            pass
        try:
            self.cobot.close()
        except Exception:
            pass
        try:
            self.lights.close()
        except Exception:
            pass


class SimulatedHardwareStrategy:
    """Executes station operations in Simulation Mode using the exact same interface as RealHardwareStrategy."""

    def __init__(self, config):
        self.output_dir = config["camera"]["output_dir"]
        self.lighting_delay = min(float(config.get("camera", {}).get("lighting_delay_sec", 0.5)), 0.35)

    def connect_all(self, bus=None):
        time.sleep(0.1)
        if bus:
            bus.emit("CONNECTION", "Cobot connected (Simulation)", device="cobot", status="SIMULATED")
            bus.emit("CONNECTION", "Relay Lights connected (Simulation)", device="relay", status="SIMULATED")
            bus.emit("CONNECTION", "Camera connected (Simulation)", device="camera", status="SIMULATED")

    def move_to_step(self, position_name, settings, stop_event=None):
        if stop_event is not None and stop_event.is_set():
            raise InterruptedError("Inspection stopped by operator.")
        time.sleep(0.45)

    def capture_at_step(self, object_name, position_name, settings):
        time.sleep(self.lighting_delay)
        return generate_simulated_capture(
            output_dir=self.output_dir,
            object_name=object_name,
            position_name=position_name,
            settings=settings,
        )

    def emergency_stop(self):
        pass

    def close_all(self):
        pass


# =====================================================================
# 4. FACADE PATTERN: Unified InspectionStation Context Manager
# =====================================================================
class InspectionStation:
    """Facade wrapping Cobot, Relay Lights, and Camera behind a single clean lifecycle."""

    def __init__(self, config, simulate=False, robot_overrides=None, event_bus=None):
        self.config = config
        self.simulate = simulate
        self.bus = event_bus or EventBus()
        self.strategy = (
            SimulatedHardwareStrategy(config)
            if simulate
            else RealHardwareStrategy(config, robot_overrides=robot_overrides)
        )

    def __enter__(self):
        mode_str = "Simulation Mode" if self.simulate else "Hardware Mode"
        self.bus.emit(
            "STATE_CHANGE",
            f"Connecting station ({mode_str})...",
            state=StationState.CONNECTING,
        )
        self.strategy.connect_all(bus=self.bus)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.strategy.close_all()


# =====================================================================
# 5. COMMAND PATTERN: Self-Contained Step Command for Each Position
# =====================================================================
class InspectionStepCommand:
    """Encapsulates a single step in the 8-position inspection trajectory."""

    def __init__(self, step_index, total_steps, object_name, position_name, settings):
        self.step_index = step_index
        self.total_steps = total_steps
        self.object_name = object_name
        self.position_name = position_name
        self.settings = settings
        self.label = settings.get("label", position_name)
        self.should_capture = bool(settings.get("capture", True))

    def execute(self, station: InspectionStation, stop_event=None):
        start_t = time.time()
        step_state = StationState.CAPTURING if self.should_capture else StationState.MOVING_SAFE

        station.bus.emit(
            "STEP_START",
            f"Step {self.step_index}/{self.total_steps}: {self.label}",
            state=step_state,
            step=self.step_index,
            total=self.total_steps,
            position=self.position_name,
            label=self.label,
        )

        station.strategy.move_to_step(self.position_name, self.settings, stop_event=stop_event)

        image_path = None
        if self.should_capture:
            image_path = station.strategy.capture_at_step(
                object_name=self.object_name,
                position_name=self.position_name,
                settings=self.settings,
            )
            duration_ms = int((time.time() - start_t) * 1000)
            station.bus.emit(
                "IMAGE_CAPTURED",
                f"Captured image at {self.label} ({duration_ms} ms)",
                step=self.step_index,
                total=self.total_steps,
                position=self.position_name,
                label=self.label,
                image_path=image_path,
                duration_ms=duration_ms,
            )
        else:
            duration_ms = int((time.time() - start_t) * 1000)
            station.bus.emit(
                "STEP_COMPLETE",
                f"Completed {self.label} ({duration_ms} ms)",
                step=self.step_index,
                total=self.total_steps,
                position=self.position_name,
                label=self.label,
                duration_ms=duration_ms,
            )

        return image_path


# =====================================================================
# ORCHESTRATOR: Coordinates the 8-Step Cycle Using All 5 Patterns
# =====================================================================
class InspectionOrchestrator:
    """Coordinates the full 8-step inspection cycle and broadcasts backend events."""

    def __init__(self, event_bus=None):
        self.bus = event_bus or EventBus()
        self.active_station = None

    def run_cycle(
        self,
        config_file,
        robot_overrides=None,
        simulate=False,
        stop_event=None,
    ):
        with open(config_file, "r") as f:
            config = yaml.safe_load(f) or {}

        object_name = config.get(
            "object_name", os.path.splitext(os.path.basename(config_file))[0]
        )
        positions = config.get("inspection_positions", {})
        total_steps = len(positions)

        commands = [
            InspectionStepCommand(idx, total_steps, object_name, pos_name, settings)
            for idx, (pos_name, settings) in enumerate(positions.items(), start=1)
        ]

        saved_images = []
        self.bus.emit(
            "LOG",
            f"Starting inspection cycle for '{object_name}' ({total_steps} steps)",
        )

        with InspectionStation(
            config=config,
            simulate=simulate,
            robot_overrides=robot_overrides,
            event_bus=self.bus,
        ) as station:
            self.active_station = station
            try:
                for cmd in commands:
                    if stop_event is not None and stop_event.is_set():
                        self.bus.emit(
                            "STATE_CHANGE",
                            "Inspection stopped by operator.",
                            state=StationState.STOPPED,
                        )
                        break

                    image_path = cmd.execute(station, stop_event=stop_event)
                    if image_path:
                        saved_images.append(image_path)
                else:
                    self.bus.emit(
                        "STATE_CHANGE",
                        f"Inspection cycle complete for '{object_name}' — returned to Load 1.",
                        state=StationState.COMPLETED,
                    )
            finally:
                self.active_station = None

        return saved_images


if __name__ == "__main__":
    import sys

    simulate_flag = "--simulate" in sys.argv
    cli_args = [a for a in sys.argv[1:] if a != "--simulate"]
    cfg_file = cli_args[0] if cli_args else "dowel.yaml"

    bus = EventBus()
    bus.subscribe(lambda ev: print(f"[{ev['timestamp']}] {ev['message']}") if ev.get("message") else None)
    InspectionOrchestrator(event_bus=bus).run_cycle(cfg_file, simulate=simulate_flag)

