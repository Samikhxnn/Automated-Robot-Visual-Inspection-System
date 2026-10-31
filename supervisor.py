import os
import socket
import threading
import time
from datetime import datetime
import yaml

from camera import MvCamera
from cobot_controller import Robot as FairinoSDK
from orchestrator import EventBus, InspectionOrchestrator, StationState


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class StationSupervisor:
    """
    Safety Watchdog, Health Monitor, and Lifecycle Supervisor for the SAMI Station.
    Subscribes to the Orchestrator's EventBus and exposes live backend telemetry to the UI.
    """

    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = base_dir
        self.lock = threading.Lock()

        # Observer EventBus shared with Orchestrator
        self.event_bus = EventBus()
        self.event_bus.subscribe(self._on_orchestrator_event)
        self.orchestrator = InspectionOrchestrator(event_bus=self.event_bus)

        # Cycle State
        self.running = False
        self.stop_event = threading.Event()
        self.current_config = None
        self.current_object = None
        self.current_step = 0
        self.total_steps = 0
        self.current_position = ""
        self.current_label = "Station Ready at Load 1"
        self.status = StationState.IDLE
        self.last_error = None
        self.last_image = None
        self.last_step_duration_ms = None
        self.logs = []

        # Backend & Hardware Connection Telemetry
        self.heartbeat_count = 0
        self.last_heartbeat = datetime.now().strftime("%H:%M:%S")
        self.connections = {
            "backend": {"status": "CONNECTED", "detail": "Supervisor Active"},
            "cobot": {"status": "CHECKING", "detail": "192.168.58.2"},
            "relay": {"status": "CHECKING", "detail": "192.168.1.100:502"},
            "camera": {"status": "CHECKING", "detail": "Hikrobot MVS"},
        }

        # Run initial probe and start background watchdog thread
        self.probe_network_devices()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()

    def _watchdog_loop(self):
        """Background watchdog that updates backend heartbeat and probes hardware connections."""
        tick = 0
        while True:
            try:
                now_str = datetime.now().strftime("%H:%M:%S")
                with self.lock:
                    self.heartbeat_count += 1
                    self.last_heartbeat = now_str
                    self.connections["backend"] = {
                        "status": "CONNECTED",
                        "detail": f"Heartbeat #{self.heartbeat_count} ({now_str})",
                    }
                    is_running = self.running
                    active_cfg = self.current_config or "dowel.yaml"

                if not is_running and tick % 2 == 0:
                    self.probe_network_devices(active_cfg)
                tick += 1
            except Exception:
                pass
            time.sleep(2.0)

    def probe_network_devices(self, config_filename="dowel.yaml"):
        """Non-blocking probe to check if Fairino Cobot, Modbus Relay, and Hikrobot Camera are connected."""
        try:
            config_path = self._resolve_config_path(config_filename)
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
            cobot_ip = cfg.get("robot", {}).get("ip", "192.168.58.2")
            relay_ip = cfg.get("relay", {}).get("ip", "192.168.1.100")
            relay_port = int(cfg.get("relay", {}).get("port", 502))

            cobot_ok = self._tcp_ping(cobot_ip, 20003, timeout=0.3) or self._tcp_ping(
                cobot_ip, 8080, timeout=0.3
            )
            relay_ok = self._tcp_ping(relay_ip, relay_port, timeout=0.3)
            camera_ok = self._check_camera_available()

            with self.lock:
                if not self.running:
                    self.connections["cobot"] = {
                        "status": "CONNECTED" if cobot_ok else "OFFLINE",
                        "detail": cobot_ip,
                    }
                    self.connections["relay"] = {
                        "status": "CONNECTED" if relay_ok else "OFFLINE",
                        "detail": f"{relay_ip}:{relay_port}",
                    }
                    self.connections["camera"] = {
                        "status": "CONNECTED" if camera_ok else "OFFLINE",
                        "detail": "Hikrobot MVS" if MvCamera is not None else "SDK Not Installed",
                    }
        except Exception:
            pass

    @staticmethod
    def _check_camera_available():
        if MvCamera is None:
            return False
        try:
            from camera import MV_CC_DEVICE_INFO_LIST, MV_GIGE_DEVICE, MV_USB_DEVICE

            dev_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, dev_list)
            return ret == 0 and dev_list.nDeviceNum > 0
        except Exception:
            return False

    @staticmethod
    def _tcp_ping(host, port, timeout=0.3):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _on_orchestrator_event(self, event):
        """Listener receiving real-time structured events from the Orchestrator's EventBus."""
        etype = event.get("type")
        msg = event.get("message", "")
        ts = event.get("timestamp", datetime.now().strftime("%H:%M:%S"))

        with self.lock:
            if msg:
                self.logs.append(f"[{ts}] {msg}")
                if len(self.logs) > 200:
                    self.logs = self.logs[-200:]

            if etype == "CONNECTION":
                dev = event.get("device")
                st = event.get("status")
                if dev in self.connections and st:
                    self.connections[dev]["status"] = st

            if "state" in event and event["state"]:
                raw_state = event["state"]
                if raw_state in (
                    StationState.PRECHECK,
                    StationState.CONNECTING,
                    StationState.MOVING_SAFE,
                    StationState.CAPTURING,
                ):
                    self.status = "scanning"
                else:
                    self.status = raw_state

            if etype == "STEP_START":
                self.current_step = event.get("step", self.current_step)
                self.total_steps = event.get("total", self.total_steps)
                self.current_position = event.get("position", "")
                self.current_label = event.get("label", "")

            elif etype == "STEP_COMPLETE":
                self.last_step_duration_ms = event.get("duration_ms")

            elif etype == "IMAGE_CAPTURED":
                self.last_step_duration_ms = event.get("duration_ms")
                image_path = event.get("image_path")
                if image_path:
                    self.last_image = os.path.relpath(image_path, self.base_dir).replace(
                        "\\", "/"
                    )

            elif etype == "STATE_CHANGE":
                if event.get("state") == StationState.COMPLETED:
                    self.current_label = "Part returned to Load 1 — Inspection Complete"
                elif event.get("state") == StationState.STOPPED:
                    self.current_label = "Cycle stopped by operator"

    def add_log(self, message):
        self.event_bus.emit("LOG", message)

    def get_state(self):
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "current_config": self.current_config,
                "current_object": self.current_object,
                "current_step": self.current_step,
                "total_steps": self.total_steps,
                "current_position": self.current_position,
                "current_label": self.current_label,
                "last_step_duration_ms": self.last_step_duration_ms,
                "last_error": self.last_error,
                "last_image": self.last_image,
                "heartbeat_count": self.heartbeat_count,
                "last_heartbeat": self.last_heartbeat,
                "connections": {k: dict(v) for k, v in self.connections.items()},
                "logs": list(self.logs),
            }

    def start_scan(self, config_filename, simulate=False):
        with self.lock:
            if self.running:
                raise RuntimeError("An inspection cycle is already in progress")

            config_path = self._resolve_config_path(config_filename)
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}

            positions = cfg.get("inspection_positions", {})
            if not positions:
                raise ValueError(f"No inspection_positions found in {config_filename}")

            self.running = True
            self.stop_event.clear()
            self.current_config = os.path.basename(config_path)
            self.current_object = cfg.get(
                "object_name", os.path.splitext(self.current_config)[0]
            )
            self.current_step = 0
            self.total_steps = len(positions)
            self.current_position = ""
            self.current_label = "Pre-flight safety check..."
            self.status = "scanning"
            self.last_error = None

        thread = threading.Thread(
            target=self._supervised_worker,
            args=(config_path, simulate),
            daemon=True,
        )
        thread.start()

    def stop_scan(self):
        with self.lock:
            if not self.running:
                return False
            self.stop_event.set()
            self.current_label = "Stopping cobot safely..."

        # Trigger immediate motion stop via active station strategy if available
        active_station = self.orchestrator.active_station
        if active_station is not None:
            active_station.strategy.emergency_stop()

        self.add_log("Supervisor: Emergency/cycle stop triggered by operator.")
        return True

    def _supervised_worker(self, config_path, simulate):
        try:
            self.orchestrator.run_cycle(
                config_file=config_path,
                simulate=simulate,
                stop_event=self.stop_event,
            )
        except InterruptedError as exc:
            self.add_log(str(exc))
            with self.lock:
                self.status = StationState.STOPPED
                self.current_label = "Cycle stopped by operator"
        except Exception as exc:
            self.add_log(f"FAULT: {exc}")
            with self.lock:
                self.status = StationState.ERROR
                self.last_error = str(exc)
                self.current_label = f"Station Fault: {exc}"
        finally:
            with self.lock:
                self.running = False
                self.current_position = ""

    def list_objects(self):
        """Discover all YAML part configurations in the project folder."""
        items = []
        for entry in sorted(os.listdir(self.base_dir)):
            if not entry.endswith((".yaml", ".yml")):
                continue
            full_path = os.path.join(self.base_dir, entry)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "r") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict) or "inspection_positions" not in data:
                    continue
                positions = data.get("inspection_positions", {})
                steps_summary = []
                for idx, (pos_key, pos_val) in enumerate(positions.items(), start=1):
                    steps_summary.append(
                        {
                            "step": idx,
                            "key": pos_key,
                            "label": pos_val.get("label", pos_key),
                            "capture": bool(pos_val.get("capture", True)),
                        }
                    )
                items.append(
                    {
                        "config_file": entry,
                        "object_name": data.get(
                            "object_name", os.path.splitext(entry)[0]
                        ),
                        "output_dir": data.get("camera", {}).get(
                            "output_dir", "captures"
                        ),
                        "total_steps": len(positions),
                        "steps": steps_summary,
                    }
                )
            except Exception:
                continue
        return items

    def list_images(self, config_filename=None):
        """Return saved images for the selected part (or all parts)."""
        objects = self.list_objects()
        target_dirs = []

        if config_filename and config_filename != "__all__":
            for obj in objects:
                if obj["config_file"] == config_filename:
                    target_dirs.append(
                        (
                            obj["config_file"],
                            obj["object_name"],
                            os.path.join(self.base_dir, obj["output_dir"]),
                        )
                    )
                    break
        else:
            for obj in objects:
                target_dirs.append(
                    (
                        obj["config_file"],
                        obj["object_name"],
                        os.path.join(self.base_dir, obj["output_dir"]),
                    )
                )

        images = []
        seen_paths = set()

        for cfg_file, obj_name, folder in target_dirs:
            if not os.path.isdir(folder):
                continue
            for fname in os.listdir(folder):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    continue
                full_path = os.path.abspath(os.path.join(folder, fname))
                if not os.path.isfile(full_path) or full_path in seen_paths:
                    continue
                seen_paths.add(full_path)

                stat = os.stat(full_path)
                rel_path = os.path.relpath(full_path, self.base_dir).replace(
                    "\\", "/"
                )
                camera_label = "Camera Capture"
                lower_name = fname.lower()
                if "position_4" in lower_name or "camera_1" in lower_name or "cam1" in lower_name:
                    camera_label = "Camera 1"
                elif "position_6" in lower_name or "camera_2" in lower_name or "cam2" in lower_name:
                    camera_label = "Camera 2"

                images.append(
                    {
                        "filename": fname,
                        "camera_label": camera_label,
                        "rel_path": rel_path,
                        "url": f"/api/image?path={rel_path}",
                        "object_name": obj_name,
                        "config_file": cfg_file,
                        "size_kb": round(stat.st_size / 1024.0, 1),
                        "mtime": stat.st_mtime,
                        "timestamp": datetime.fromtimestamp(
                            stat.st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

        images.sort(key=lambda x: x["mtime"], reverse=True)
        return images

    def _resolve_config_path(self, config_filename):
        safe_name = os.path.basename(config_filename)
        full_path = os.path.abspath(os.path.join(self.base_dir, safe_name))
        if not full_path.startswith(self.base_dir) or not os.path.isfile(full_path):
            raise FileNotFoundError(f"Configuration file not found: {safe_name}")
        return full_path
