import os
import sys
import ctypes
from datetime import datetime
from ctypes import (
    byref, c_ubyte, c_void_p, cast, POINTER, sizeof, memset
)

import cv2
import numpy as np

# Add MVS Python wrapper path
if "/opt/MVS/Samples/64/Python" not in sys.path:
    sys.path.append("/opt/MVS/Samples/64/Python")

try:
    from MvImport.MvCameraControl_class import *
except ImportError:
    try:
        from MvCameraControl_class import *
    except ImportError:
        MvCamera = None


class CameraCapture:
    def __init__(self, config):
        self.serial_number = config.get("serial_number", "").strip()
        self.output_dir = config["output_dir"]
        self.timeout_ms = int(config.get("frame_timeout_ms", 2000))

        self.camera = None
        self.grabbing = False

        os.makedirs(self.output_dir, exist_ok=True)

    def open(self):
        if self.camera is not None:
            return

        if MvCamera is None:
            raise RuntimeError(
                "Hikrobot MVS Python SDK (MvCameraControl_class) is not installed"
            )

        device_list = MV_CC_DEVICE_INFO_LIST()
        device_types = MV_GIGE_DEVICE | MV_USB_DEVICE

        ret = MvCamera.MV_CC_EnumDevices(
            device_types, device_list
        )
        if ret != 0:
            raise RuntimeError(
                f"Camera enumeration failed: 0x{ret:x}"
            )

        if device_list.nDeviceNum == 0:
            raise RuntimeError("No Hikrobot camera found")

        selected_info = None

        for i in range(device_list.nDeviceNum):
            info = cast(
                device_list.pDeviceInfo[i],
                POINTER(MV_CC_DEVICE_INFO)
            ).contents

            serial = self._get_serial_number(info)

            if not self.serial_number or serial == self.serial_number:
                selected_info = device_list.pDeviceInfo[i]
                break

        if selected_info is None:
            raise RuntimeError(
                f"Camera serial not found: {self.serial_number}"
            )

        camera = MvCamera()

        ret = camera.MV_CC_CreateHandle(selected_info)
        if ret != 0:
            raise RuntimeError(
                f"CreateHandle failed: 0x{ret:x}"
            )

        ret = camera.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            camera.MV_CC_DestroyHandle()
            raise RuntimeError(
                f"OpenDevice failed: 0x{ret:x}"
            )

        # Software-controlled acquisition; exposure is configured manually.
        ret = camera.MV_CC_SetEnumValue(
            "TriggerMode", MV_TRIGGER_MODE_OFF
        )
        if ret != 0:
            camera.MV_CC_CloseDevice()
            camera.MV_CC_DestroyHandle()
            raise RuntimeError(
                f"Could not disable trigger mode: 0x{ret:x}"
            )

        ret = camera.MV_CC_StartGrabbing()
        if ret != 0:
            camera.MV_CC_CloseDevice()
            camera.MV_CC_DestroyHandle()
            raise RuntimeError(
                f"StartGrabbing failed: 0x{ret:x}"
            )

        self.camera = camera
        self.grabbing = True
        print("Hikrobot camera opened")

    def _get_serial_number(self, info):
        try:
            if info.nTLayerType == MV_GIGE_DEVICE:
                return bytes(
                    info.SpecialInfo.stGigEInfo.chSerialNumber
                ).split(b"\0", 1)[0].decode(
                    "ascii", errors="ignore"
                )

            if info.nTLayerType == MV_USB_DEVICE:
                return bytes(
                    info.SpecialInfo.stUsb3VInfo.chSerialNumber
                ).split(b"\0", 1)[0].decode(
                    "ascii", errors="ignore"
                )
        except Exception:
            pass

        return ""

    def set_exposure(self, exposure_time_us):
        if self.camera is None:
            raise RuntimeError("Open camera first")

        exposure_time_us = float(exposure_time_us)

        if exposure_time_us <= 0:
            raise ValueError("Exposure time must be positive")

        ret = self.camera.MV_CC_SetEnumValue(
            "ExposureAuto", 0
        )
        if ret != 0:
            raise RuntimeError(
                f"Could not disable auto exposure: 0x{ret:x}"
            )

        ret = self.camera.MV_CC_SetFloatValue(
            "ExposureTime", exposure_time_us
        )
        if ret != 0:
            raise RuntimeError(
                f"Setting exposure failed: 0x{ret:x}"
            )

        print(f"Exposure: {exposure_time_us} us")

    def capture(self, position_name, exposure_time_us):
        if self.camera is None or not self.grabbing:
            raise RuntimeError("Open camera before capturing")

        self.set_exposure(exposure_time_us)

        frame = MV_FRAME_OUT()
        memset(byref(frame), 0, sizeof(frame))

        ret = self.camera.MV_CC_GetImageBuffer(
            frame, self.timeout_ms
        )
        if ret != 0:
            raise RuntimeError(
                f"GetImageBuffer failed: 0x{ret:x}"
            )

        try:
            width = int(frame.stFrameInfo.nWidth)
            height = int(frame.stFrameInfo.nHeight)
            pixel_type = frame.stFrameInfo.enPixelType
            frame_length = int(frame.stFrameInfo.nFrameLen)

            rgb_buffer_size = width * height * 3
            rgb_buffer = (c_ubyte * rgb_buffer_size)()

            convert = MV_CC_PIXEL_CONVERT_PARAM()
            memset(byref(convert), 0, sizeof(convert))

            convert.nWidth = width
            convert.nHeight = height
            convert.pSrcData = cast(
                frame.pBufAddr, POINTER(c_ubyte)
            )
            convert.nSrcDataLen = frame_length
            convert.enSrcPixelType = pixel_type
            convert.enDstPixelType = PixelType_Gvsp_BGR8_Packed
            convert.pDstBuffer = cast(
                rgb_buffer, POINTER(c_ubyte)
            )
            convert.nDstBufferSize = rgb_buffer_size

            ret = self.camera.MV_CC_ConvertPixelType(convert)
            if ret != 0:
                raise RuntimeError(
                    f"Pixel conversion failed: 0x{ret:x}"
                )

            image = np.frombuffer(
                rgb_buffer, dtype=np.uint8
            ).reshape(height, width, 3).copy()

        finally:
            self.camera.MV_CC_FreeImageBuffer(frame)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{position_name}_{timestamp}.jpg"
        path = os.path.join(self.output_dir, filename)

        if not cv2.imwrite(path, image):
            raise RuntimeError(f"Failed to save image: {path}")

        print(f"Image saved: {path}")
        return path

    def close(self):
        if self.camera is None:
            return

        try:
            if self.grabbing:
                self.camera.MV_CC_StopGrabbing()
        finally:
            self.camera.MV_CC_CloseDevice()
            self.camera.MV_CC_DestroyHandle()
            self.camera = None
            self.grabbing = False
            print("Hikrobot camera closed")
