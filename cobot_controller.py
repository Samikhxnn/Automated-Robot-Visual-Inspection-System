import os
import sys
import time
import yaml

# Add Fairino Python SDK path
FAIRINO_SDK_LINUX_DIR = "/home/user2/Downloads/fairino-python-sdk-main/linux"
if os.path.isdir(FAIRINO_SDK_LINUX_DIR) and FAIRINO_SDK_LINUX_DIR not in sys.path:
    sys.path.append(FAIRINO_SDK_LINUX_DIR)

try:
    from fairino import Robot
except ImportError:
    Robot = None


DEFAULT_ROBOT_CONFIG = {
    "ip": "192.168.58.2",
    "tool": 0,
    "user": 0,
    "vel": 20.0,
    "acc": 0.0,
    "ovl": 100.0,
    "blendT": -1.0,
    "blendR": -1.0,
    "config": -1,
    "exaxis_pos": [0.0, 0.0, 0.0, 0.0],
    "offset_flag": 0,
    "offset_pos": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "move_timeout_sec": 60.0,
    "poll_interval_sec": 0.2,
    "required_stable_readings": 5,
    "joint_stability_deg": 0.2,
    "cart_tolerance_mm": 2.0,
    "cart_stability_mm": 0.5,
}


def joint_distance(a, b):
    """Calculate the shortest angular distance in degrees."""
    return abs((float(a) - float(b) + 180) % 360 - 180)


def joints_match(current, target, tolerance):
    """Check whether all six joints match the target within tolerance."""
    if len(current) != 6 or len(target) != 6:
        return False

    return all(
        joint_distance(current[i], target[i]) <= tolerance
        for i in range(6)
    )


def carts_match(current_pose, target_pose, pos_tolerance_mm=2.0, ori_tolerance_deg=2.0):
    """Check whether Cartesian pose [x, y, z, rx, ry, rz] matches target within tolerance."""
    if len(current_pose) != 6 or len(target_pose) != 6:
        return False

    pos_ok = all(
        abs(float(current_pose[i]) - float(target_pose[i])) <= pos_tolerance_mm
        for i in range(3)
    )
    ori_ok = all(
        joint_distance(current_pose[i], target_pose[i]) <= ori_tolerance_deg
        for i in range(3, 6)
    )
    return pos_ok and ori_ok


def extract_carts(settings):
    """Extract Cartesian pose list [x, y, z, rx, ry, rz] from a YAML position dict."""
    for key in ("carts", "cart", "cartesian", "desc_pos"):
        val = settings.get(key)
        if val is not None and len(val) == 6:
            return [float(x) for x in val]
    return None


def extract_joints(settings):
    """Extract joint angles list [j1, j2, j3, j4, j5, j6] from a YAML position dict."""
    for key in ("joints", "joint", "joint_pos"):
        val = settings.get(key)
        if val is not None and len(val) == 6:
            return [float(x) for x in val]
    return None


class FairinoController:
    """
    Customizable controller for Fairino Cobot using
    /home/user2/Downloads/fairino-python-sdk-main/linux/fairino/Robot.py.

    Controls the cobot using MoveJ and MoveCart (and MoveL) based on the
    `joints` and `carts` configured in your YAML files.
    """

    def __init__(self, config=None):
        merged = dict(DEFAULT_ROBOT_CONFIG)
        if config:
            merged.update(config)

        self.ip = str(merged["ip"])
        self.tool = int(merged["tool"])
        self.user = int(merged["user"])
        self.vel = float(merged["vel"])
        self.acc = float(merged["acc"])
        self.ovl = float(merged["ovl"])
        self.blendT = float(merged["blendT"])
        self.blendR = float(merged["blendR"])
        self.config = int(merged["config"])
        self.exaxis_pos = [float(x) for x in merged["exaxis_pos"]]
        self.offset_flag = int(merged["offset_flag"])
        self.offset_pos = [float(x) for x in merged["offset_pos"]]

        self.move_timeout_sec = float(merged["move_timeout_sec"])
        self.poll_interval_sec = float(merged["poll_interval_sec"])
        self.required_stable_readings = int(merged["required_stable_readings"])
        self.joint_stability_deg = float(merged["joint_stability_deg"])
        self.cart_tolerance_mm = float(merged["cart_tolerance_mm"])
        self.cart_stability_mm = float(merged["cart_stability_mm"])

        self.robot = None

    def update_parameters(self, **kwargs):
        """Update controller motion parameters dynamically at runtime."""
        if "ip" in kwargs and kwargs["ip"] is not None:
            self.ip = str(kwargs["ip"])
        if "tool" in kwargs and kwargs["tool"] is not None:
            self.tool = int(kwargs["tool"])
        if "user" in kwargs and kwargs["user"] is not None:
            self.user = int(kwargs["user"])
        if "vel" in kwargs and kwargs["vel"] is not None:
            self.vel = float(kwargs["vel"])
        if "acc" in kwargs and kwargs["acc"] is not None:
            self.acc = float(kwargs["acc"])
        if "ovl" in kwargs and kwargs["ovl"] is not None:
            self.ovl = float(kwargs["ovl"])
        if "blendT" in kwargs and kwargs["blendT"] is not None:
            self.blendT = float(kwargs["blendT"])
        if "blendR" in kwargs and kwargs["blendR"] is not None:
            self.blendR = float(kwargs["blendR"])
        if "config" in kwargs and kwargs["config"] is not None:
            self.config = int(kwargs["config"])
        if "offset_flag" in kwargs and kwargs["offset_flag"] is not None:
            self.offset_flag = int(kwargs["offset_flag"])
        if "offset_pos" in kwargs and kwargs["offset_pos"] is not None:
            self.offset_pos = [float(x) for x in kwargs["offset_pos"]]

    def get_parameters(self):
        """Return current motion configuration dictionary."""
        return {
            "ip": self.ip,
            "tool": self.tool,
            "user": self.user,
            "vel": self.vel,
            "acc": self.acc,
            "ovl": self.ovl,
            "blendT": self.blendT,
            "blendR": self.blendR,
            "config": self.config,
            "offset_flag": self.offset_flag,
            "offset_pos": list(self.offset_pos),
        }

    def connect(self):
        """Connect to the Fairino cobot RPC server."""
        if self.robot is not None:
            return self.robot

        if Robot is None:
            raise RuntimeError(
                f"Fairino Python SDK not found at {FAIRINO_SDK_LINUX_DIR}"
            )

        self.robot = Robot.RPC(self.ip)
        print(f"Fairino cobot connected: {self.ip}")
        return self.robot

    def close(self):
        """Close the RPC connection."""
        if self.robot is not None:
            if hasattr(self.robot, "CloseRPC"):
                try:
                    self.robot.CloseRPC()
                except Exception:
                    pass
            self.robot = None
            print("Fairino cobot connection closed")

    def enable_robot(self, enable=True):
        """Set robot to automatic mode (0) and enable servos."""
        self._ensure_connected()
        if hasattr(self.robot, "Mode"):
            self.robot.Mode(0)
        if hasattr(self.robot, "RobotEnable"):
            ret = self.robot.RobotEnable(1 if enable else 0)
            if ret != 0:
                raise RuntimeError(f"RobotEnable failed with error code: {ret}")

    def stop_motion(self):
        """Immediately stop robot motion."""
        if self.robot is None:
            return
        if hasattr(self.robot, "StopMotion"):
            try:
                self.robot.StopMotion()
            except Exception as exc:
                print(f"StopMotion warning: {exc}")

    def reset_errors(self):
        """Reset clearable errors on the cobot."""
        self._ensure_connected()
        return self.robot.ResetAllError()

    def get_joint_positions(self):
        """
        Return the 6 current joint angles in degrees: [j1, j2, j3, j4, j5, j6].
        Handles Robot.py returning (0, joints) on success or int error_code on error.
        """
        self._ensure_connected()
        res = self.robot.GetActualJointPosDegree(1)
        if isinstance(res, (tuple, list)):
            error_code = res[0]
            if error_code == 0 and len(res) > 1 and res[1] is not None:
                return [float(j) for j in res[1]]
            raise RuntimeError(f"GetActualJointPosDegree failed: {error_code}")
        raise RuntimeError(f"GetActualJointPosDegree failed: {res}")

    def get_tcp_pose(self):
        """
        Return the current 6-DOF Cartesian TCP pose: [x, y, z, rx, ry, rz].
        Handles Robot.py returning (0, tcp_pose) on success or int error_code on error.
        """
        self._ensure_connected()
        res = self.robot.GetActualTCPPose(1)
        if isinstance(res, (tuple, list)):
            error_code = res[0]
            if error_code == 0 and len(res) > 1 and res[1] is not None:
                return [float(p) for p in res[1]]
            raise RuntimeError(f"GetActualTCPPose failed: {error_code}")
        raise RuntimeError(f"GetActualTCPPose failed: {res}")

    def move_j(
        self,
        joints_deg,
        desc_pos=None,
        tool=None,
        user=None,
        vel=None,
        acc=None,
        ovl=None,
        exaxis_pos=None,
        blendT=None,
        offset_flag=None,
        offset_pos=None,
    ):
        """
        Joint space motion using Robot.RPC.MoveJ:
        MoveJ(joint_pos, tool, user, desc_pos=[0,0,0,0,0,0], vel=20.0, acc=0.0, ovl=100.0,
              exaxis_pos=[0,0,0,0], blendT=-1.0, offset_flag=0, offset_pos=[0,0,0,0,0,0])

        Note: If desc_pos is omitted or all zeros, Robot.py automatically computes
        forward kinematics via GetForwardKin(joint_pos).
        """
        self._ensure_connected()

        if len(joints_deg) != 6:
            raise ValueError("joints_deg must contain 6 joint angles in degrees")

        joint_pos = [float(j) for j in joints_deg]
        tool_val = self.tool if tool is None else int(tool)
        user_val = self.user if user is None else int(user)
        vel_val = self.vel if vel is None else float(vel)
        acc_val = self.acc if acc is None else float(acc)
        ovl_val = self.ovl if ovl is None else float(ovl)
        blend_t_val = self.blendT if blendT is None else float(blendT)
        exaxis_val = (
            list(self.exaxis_pos)
            if exaxis_pos is None
            else [float(x) for x in exaxis_pos]
        )
        off_flag = self.offset_flag if offset_flag is None else int(offset_flag)
        off_pos = (
            list(self.offset_pos)
            if offset_pos is None
            else [float(x) for x in offset_pos]
        )
        desc_pos_val = (
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            if desc_pos is None
            else [float(p) for p in desc_pos]
        )

        ret = self.robot.MoveJ(
            joint_pos,
            tool_val,
            user_val,
            desc_pos=desc_pos_val,
            vel=vel_val,
            acc=acc_val,
            ovl=ovl_val,
            exaxis_pos=exaxis_val,
            blendT=blend_t_val,
            offset_flag=off_flag,
            offset_pos=off_pos,
        )
        if ret != 0:
            raise RuntimeError(f"MoveJ failed with error code: {ret}")

        print(
            f"MoveJ complete -> joints={joint_pos}, tool={tool_val}, "
            f"user={user_val}, vel={vel_val}"
        )
        return ret

    def move_cart(
        self,
        carts_pose,
        tool=None,
        user=None,
        vel=None,
        acc=None,
        ovl=None,
        blendT=None,
        config=None,
    ):
        """
        Cartesian point-to-point motion using Robot.RPC.MoveCart:
        MoveCart(desc_pos, tool, user, vel=20.0, acc=0.0, ovl=100.0, blendT=-1.0, config=-1)
        """
        self._ensure_connected()

        if len(carts_pose) != 6:
            raise ValueError(
                "carts_pose must contain 6 Cartesian values [x, y, z, rx, ry, rz]"
            )

        desc_pos = [float(p) for p in carts_pose]
        tool_val = self.tool if tool is None else int(tool)
        user_val = self.user if user is None else int(user)
        vel_val = self.vel if vel is None else float(vel)
        acc_val = self.acc if acc is None else float(acc)
        ovl_val = self.ovl if ovl is None else float(ovl)
        blend_t_val = self.blendT if blendT is None else float(blendT)
        cfg_val = self.config if config is None else int(config)

        ret = self.robot.MoveCart(
            desc_pos,
            tool_val,
            user_val,
            vel=vel_val,
            acc=acc_val,
            ovl=ovl_val,
            blendT=blend_t_val,
            config=cfg_val,
        )
        if ret != 0:
            raise RuntimeError(f"MoveCart failed with error code: {ret}")

        print(
            f"MoveCart complete -> carts={desc_pos}, tool={tool_val}, "
            f"user={user_val}, vel={vel_val}"
        )
        return ret

    def move_l(
        self,
        carts_pose,
        joints_deg=None,
        tool=None,
        user=None,
        vel=None,
        acc=None,
        ovl=None,
        blendR=None,
        exaxis_pos=None,
        search=0,
        offset_flag=None,
        offset_pos=None,
        config=None,
    ):
        """
        Cartesian linear motion using Robot.RPC.MoveL:
        MoveL(desc_pos, tool, user, joint_pos=[0,0,0,0,0,0], vel=20.0, acc=0.0, ovl=100.0, ...)
        """
        self._ensure_connected()

        if len(carts_pose) != 6:
            raise ValueError(
                "carts_pose must contain 6 Cartesian values [x, y, z, rx, ry, rz]"
            )

        desc_pos = [float(p) for p in carts_pose]
        tool_val = self.tool if tool is None else int(tool)
        user_val = self.user if user is None else int(user)
        vel_val = self.vel if vel is None else float(vel)
        acc_val = self.acc if acc is None else float(acc)
        ovl_val = self.ovl if ovl is None else float(ovl)
        blend_r_val = self.blendR if blendR is None else float(blendR)
        exaxis_val = (
            list(self.exaxis_pos)
            if exaxis_pos is None
            else [float(x) for x in exaxis_pos]
        )
        off_flag = self.offset_flag if offset_flag is None else int(offset_flag)
        off_pos = (
            list(self.offset_pos)
            if offset_pos is None
            else [float(x) for x in offset_pos]
        )
        cfg_val = self.config if config is None else int(config)
        joint_pos = (
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            if joints_deg is None
            else [float(j) for j in joints_deg]
        )

        ret = self.robot.MoveL(
            desc_pos,
            tool_val,
            user_val,
            joint_pos=joint_pos,
            vel=vel_val,
            acc=acc_val,
            ovl=ovl_val,
            blendR=blend_r_val,
            exaxis_pos=exaxis_val,
            search=int(search),
            offset_flag=off_flag,
            offset_pos=off_pos,
            config=cfg_val,
        )
        if ret != 0:
            raise RuntimeError(f"MoveL failed with error code: {ret}")

        print(
            f"MoveL complete -> carts={desc_pos}, tool={tool_val}, "
            f"user={user_val}, vel={vel_val}"
        )
        return ret

    def wait_until_joints_stable(
        self,
        target_joints,
        tolerance_deg=2.0,
        timeout_sec=None,
        stop_event=None,
    ):
        """
        Poll actual joint angles until they match target_joints within
        tolerance_deg and remain stable for required_stable_readings.
        """
        self._ensure_connected()

        timeout = (
            self.move_timeout_sec if timeout_sec is None else float(timeout_sec)
        )
        tolerance = float(tolerance_deg)
        deadline = time.time() + timeout
        stable_count = 0
        previous_joints = None

        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Scan/motion cancelled by user")

            try:
                current_joints = self.get_joint_positions()
            except RuntimeError as exc:
                print(f"Joint read warning: {exc}")
                time.sleep(self.poll_interval_sec)
                continue

            matched = joints_match(current_joints, target_joints, tolerance)
            joints_stable = (
                previous_joints is not None
                and all(
                    joint_distance(current_joints[i], previous_joints[i])
                    <= self.joint_stability_deg
                    for i in range(6)
                )
            )

            if matched and joints_stable:
                stable_count += 1
            elif matched:
                stable_count = 1
            else:
                stable_count = 0

            if stable_count >= self.required_stable_readings:
                return current_joints

            previous_joints = current_joints
            time.sleep(self.poll_interval_sec)

        raise TimeoutError(
            f"Timed out waiting for cobot to reach target joints {target_joints}"
        )

    def wait_until_carts_stable(
        self,
        target_carts,
        tolerance_mm=2.0,
        tolerance_deg=2.0,
        timeout_sec=None,
        stop_event=None,
    ):
        """
        Poll actual TCP pose until it matches target_carts [x, y, z, rx, ry, rz]
        and remains stable for required_stable_readings.
        """
        self._ensure_connected()

        timeout = (
            self.move_timeout_sec if timeout_sec is None else float(timeout_sec)
        )
        deadline = time.time() + timeout
        stable_count = 0
        previous_pose = None

        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Scan/motion cancelled by user")

            try:
                current_pose = self.get_tcp_pose()
            except RuntimeError as exc:
                print(f"TCP pose read warning: {exc}")
                time.sleep(self.poll_interval_sec)
                continue

            matched = carts_match(
                current_pose,
                target_carts,
                pos_tolerance_mm=float(tolerance_mm),
                ori_tolerance_deg=float(tolerance_deg),
            )
            pose_stable = (
                previous_pose is not None
                and all(
                    abs(current_pose[i] - previous_pose[i]) <= self.cart_stability_mm
                    for i in range(3)
                )
                and all(
                    joint_distance(current_pose[i], previous_pose[i])
                    <= self.joint_stability_deg
                    for i in range(3, 6)
                )
            )

            if matched and pose_stable:
                stable_count += 1
            elif matched:
                stable_count = 1
            else:
                stable_count = 0

            if stable_count >= self.required_stable_readings:
                return current_pose

            previous_pose = current_pose
            time.sleep(self.poll_interval_sec)

        raise TimeoutError(
            f"Timed out waiting for cobot to reach target carts {target_carts}"
        )

    def move_to_position_config(self, position_name, settings, stop_event=None):
        """
        Move the cobot to a YAML-configured inspection position using either
        MoveJ (based on `joints`) or MoveCart (based on `carts`).

        In YAML `inspection_positions.<position_name>`:
          - move_type: "MoveJ" | "MoveCart" | "MoveL" (optional; auto-detected if omitted)
          - joints: [j1, j2, j3, j4, j5, j6]
          - carts:  [x, y, z, rx, ry, rz]
          - vel, acc, ovl, tool, user, blendT, blendR, tolerance_deg, tolerance_mm (optional)
        """
        joints = extract_joints(settings)
        carts = extract_carts(settings)

        raw_move_type = str(settings.get("move_type", "")).strip().lower()
        if not raw_move_type:
            # Auto-select MoveCart if carts is provided without joints, otherwise MoveJ
            if carts is not None and joints is None:
                raw_move_type = "movecart"
            else:
                raw_move_type = "movej"

        vel = settings.get("vel", None)
        acc = settings.get("acc", None)
        ovl = settings.get("ovl", None)
        tool = settings.get("tool", None)
        user = settings.get("user", None)
        blend_t = settings.get("blendT", None)
        blend_r = settings.get("blendR", None)
        config_ik = settings.get("config", None)
        tolerance_deg = float(settings.get("tolerance_deg", 2.0))
        tolerance_mm = float(settings.get("tolerance_mm", self.cart_tolerance_mm))

        if raw_move_type in ("movecart", "move_cart", "cart", "carts"):
            if carts is None:
                raise ValueError(
                    f"Position '{position_name}' specifies MoveCart but has no 'carts' [x, y, z, rx, ry, rz] in YAML"
                )
            self.move_cart(
                carts_pose=carts,
                tool=tool,
                user=user,
                vel=vel,
                acc=acc,
                ovl=ovl,
                blendT=blend_t,
                config=config_ik,
            )
            if joints is not None:
                self.wait_until_joints_stable(
                    joints,
                    tolerance_deg=tolerance_deg,
                    stop_event=stop_event,
                )
            else:
                self.wait_until_carts_stable(
                    carts,
                    tolerance_mm=tolerance_mm,
                    tolerance_deg=tolerance_deg,
                    stop_event=stop_event,
                )

        elif raw_move_type in ("movel", "move_l"):
            if carts is None:
                raise ValueError(
                    f"Position '{position_name}' specifies MoveL but has no 'carts' [x, y, z, rx, ry, rz] in YAML"
                )
            self.move_l(
                carts_pose=carts,
                joints_deg=joints,
                tool=tool,
                user=user,
                vel=vel,
                acc=acc,
                ovl=ovl,
                blendR=blend_r,
                config=config_ik,
            )
            if joints is not None:
                self.wait_until_joints_stable(
                    joints,
                    tolerance_deg=tolerance_deg,
                    stop_event=stop_event,
                )
            else:
                self.wait_until_carts_stable(
                    carts,
                    tolerance_mm=tolerance_mm,
                    tolerance_deg=tolerance_deg,
                    stop_event=stop_event,
                )

        else:
            # Default: MoveJ using joints (and optional carts as desc_pos)
            if joints is None:
                raise ValueError(
                    f"Position '{position_name}' specifies MoveJ but has no 'joints' [j1..j6] in YAML"
                )
            self.move_j(
                joints_deg=joints,
                desc_pos=carts,
                tool=tool,
                user=user,
                vel=vel,
                acc=acc,
                ovl=ovl,
                blendT=blend_t,
            )
            self.wait_until_joints_stable(
                joints,
                tolerance_deg=tolerance_deg,
                stop_event=stop_event,
            )

    def _ensure_connected(self):
        if self.robot is None:
            self.connect()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Control Fairino Cobot via MoveJ and MoveCart using YAML joints and carts"
    )
    parser.add_argument(
        "--config",
        default="dowel.yaml",
        help="Path to YAML configuration file (default: dowel.yaml)",
    )
    parser.add_argument("--ip", default=None, help="Override Fairino Cobot IP address")
    parser.add_argument("--vel", type=float, default=None, help="Override velocity (0-100)")
    parser.add_argument("--acc", type=float, default=None, help="Override acceleration (0-100)")
    parser.add_argument("--tool", type=int, default=None, help="Override tool frame (0-14)")
    parser.add_argument("--user", type=int, default=None, help="Override user frame (0-14)")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read and print current joint angles (deg) and Cartesian TCP pose",
    )
    parser.add_argument(
        "--move-j",
        nargs=6,
        type=float,
        metavar=("J1", "J2", "J3", "J4", "J5", "J6"),
        help="Execute MoveJ with 6 joint angles in degrees",
    )
    parser.add_argument(
        "--move-cart",
        nargs=6,
        type=float,
        metavar=("X", "Y", "Z", "RX", "RY", "RZ"),
        help="Execute MoveCart with 6 Cartesian values [x, y, z, rx, ry, rz]",
    )
    parser.add_argument(
        "--move-l",
        nargs=6,
        type=float,
        metavar=("X", "Y", "Z", "RX", "RY", "RZ"),
        help="Execute MoveL with 6 Cartesian values [x, y, z, rx, ry, rz]",
    )
    parser.add_argument(
        "--position",
        default=None,
        help="Move to a specific inspection position defined in the YAML file",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Move sequentially through all inspection_positions in the YAML file",
    )

    args = parser.parse_args()

    robot_cfg = {}
    positions_cfg = {}
    if os.path.isfile(args.config):
        with open(args.config, "r") as f:
            yaml_data = yaml.safe_load(f) or {}
            robot_cfg = yaml_data.get("robot", {})
            positions_cfg = yaml_data.get("inspection_positions", {})

    controller = FairinoController(robot_cfg)
    controller.update_parameters(
        ip=args.ip,
        vel=args.vel,
        acc=args.acc,
        tool=args.tool,
        user=args.user,
    )

    try:
        controller.connect()
        if args.status:
            print("Current Joints (deg):", controller.get_joint_positions())
            print("Current Carts / TCP Pose:", controller.get_tcp_pose())

        if args.move_j:
            controller.move_j(args.move_j)

        if args.move_cart:
            controller.move_cart(args.move_cart)

        if args.move_l:
            controller.move_l(args.move_l)

        if args.position:
            if args.position not in positions_cfg:
                raise KeyError(
                    f"Position '{args.position}' not found in {args.config}"
                )
            controller.move_to_position_config(
                args.position, positions_cfg[args.position]
            )

        if args.run_all:
            for pos_name, pos_settings in positions_cfg.items():
                print(f"Moving to YAML position: {pos_name}")
                controller.move_to_position_config(pos_name, pos_settings)
    finally:
        controller.close()
