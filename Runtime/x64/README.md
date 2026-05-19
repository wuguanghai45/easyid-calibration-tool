# MVSDK Windows x64 Runtime

Place the vendor **x64** runtime files here. The calibration tool loads:

- `MVSDKmd.dll` (required)

If `LoadLibrary` fails with a missing dependency error, copy **all** DLLs from the SDK installer `Runtime/x64` folder into this directory (not only `MVSDKmd.dll`).

No `IMV_SDK_LIB` environment variable is required when `MVSDKmd.dll` is present in this path.
