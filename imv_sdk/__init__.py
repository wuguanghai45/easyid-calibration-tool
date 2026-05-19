"""Huaray IMV MVSDK Python bindings."""

from imv_sdk.IMVDefines import IMV_OK

__all__ = ["IMV_OK", "MvCamera"]


def __getattr__(name: str):
    if name == "MvCamera":
        from imv_sdk.IMVApi import MvCamera

        return MvCamera
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
