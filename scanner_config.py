"""Configuration constants for scanner calibration collection."""

from __future__ import annotations


# Candidate GenICam feature names for common scanner/camera models.
USERSET_SELECTOR_FEATURES = (
    "UserSetSelector",
    "DeviceUserSetSelector",
    "ConfigType",
    "DeviceConfigSelector",
)

SOFTWARE_USERSET_SYMBOLS = (
    "Software",
    "Soft",
    "UserSet0",
    "Default",
)

HARDWARE_USERSET_SYMBOLS = (
    "Hardware",
    "Hard",
    "UserSet1",
    "Custom",
)

USERSET_SAVE_COMMANDS = (
    "UserSetSave",
    "DeviceUserSetSave",
)

USERSET_LOAD_COMMANDS = (
    "UserSetLoad",
    "DeviceUserSetLoad",
)

TRIGGER_MODE_FEATURES = (
    "TriggerMode",
    "AcquisitionTriggerMode",
)

TRIGGER_MODE_ON_SYMBOLS = (
    "On",
    "True",
)

TRIGGER_SOURCE_FEATURES = (
    "TriggerSource",
    "AcquisitionTriggerSource",
)

TRIGGER_SOURCE_SOFTWARE_SYMBOLS = (
    "Software",
    "Soft",
)

TRIGGER_COMMAND_FEATURES = (
    "TriggerSoftware",
    "SoftwareTrigger",
    "AcquisitionStart",
)

FEATURE_ROOT_NAMES = (
    "Root",
    "AcquisitionControl",
    "UserSetControl",
)

ENUM_SYMBOL_BUFFER_SIZE = 256
DEFAULT_FRAME_TIMEOUT_MS = 2000
DEFAULT_BUFFER_COUNT = 3

# Factory GigE network defaults (applied when device IP does not match).
TARGET_DEVICE_IP = "192.168.40.200"
TARGET_GATEWAY = "192.168.40.1"
TARGET_SUBNET_MASK = "255.255.255.0"
GIGE_IP_SETTLE_SEC = 2.0
