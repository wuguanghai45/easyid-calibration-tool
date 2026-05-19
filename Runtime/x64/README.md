# MVSDK Windows x64 Runtime

Copy the **entire** `Runtime/x64` folder from the Huaray/IMV SDK installer into this directory.

`MVSDKmd.dll` alone is not enough — it depends on other DLLs in the same folder (e.g. GenICam / transport libraries). If only one DLL is present, `LoadLibrary` will fail.

After copy, this folder should contain multiple `.dll` files (typical install: 5–20+ files).

`IMV_SDK_LIB` is optional when `MVSDKmd.dll` is here and dependencies are alongside it.
