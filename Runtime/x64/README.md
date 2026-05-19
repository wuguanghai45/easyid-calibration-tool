# MVSDK Windows x64 Runtime

`MVSDKmd.dll` **cannot run alone**. Copy the **entire** `Runtime/x64` folder from the IMV/Huaray SDK installer.

## Required vendor DLLs (alongside MVSDKmd.dll)

| DLL |
|-----|
| TinyXmlmd.dll |
| GCBase_MD_VC120_v3_0.dll |
| GenApi_MD_VC120_v3_0.dll |
| CLProtocol_MD_VC120_v3_0.dll |
| MVlog4cppmd.dll |
| ImageConvert.dll |
| ImageSave.dll |
| CamUpgradeModule.dll |
| MSVCP120.dll |
| MSVCR120.dll |

If `MSVCP120.dll` / `MSVCR120.dll` are missing, install **Microsoft Visual C++ 2013 Redistributable (x64)**.

## Verify on Windows

```bat
python scripts\check_mvsdk_runtime.py
```

Then:

```bat
python read_scanner_calibration.py --list-devices
```
