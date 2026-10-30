# Making BasilBACnetExplorer.exe

You only build once; the resulting `.exe` runs on any Windows PC **without Python**.

## Option A – on your Windows PC (5 minutes)
1. Install Python from python.org (tick **Add python.exe to PATH**; keep **tcl/tk** selected).
   `build_exe.bat` offers to install it with winget if it's missing.
2. Double-click **`build_exe.bat`**.
3. The `dist` folder opens with:
   - `BasilBACnetExplorer.exe` – the application (green logo, no console window)
   - `BasilBACnetSimulator.exe` – test device simulator
   - `graphics\` – drop extra equipment `.py` files here; they load without rebuilding

Which Windows it runs on depends on the Python you build with:

| Built with | Runs on |
|---|---|
| Python 3.12 64-bit (default) | Windows 8.1 / 10 / 11, 64-bit |
| Python 3.8 **32-bit** | Windows 7 SP1, 8, 8.1, 10, 11 – 32 and 64-bit (most compatible) |

## Option B – in the cloud with GitHub (no Python on your PC)
1. Create a GitHub repository and upload this whole folder (including `.github`).
2. Open the **Actions** tab ▸ **Build Windows exe** ▸ *Run workflow*.
3. When it finishes, download both zips from the run page:
   `BasilBACnetExplorer-Windows-10-11-64bit` and `BasilBACnetExplorer-Windows-7-and-later-32bit`.
   Pushing a tag such as `v1.2.0` also publishes them as a GitHub Release.

## Notes
* First start of a single-file exe takes a few seconds (it unpacks itself).
* Some antivirus programs flag new unsigned PyInstaller programs. If that happens, add an
  exception, or sign the exe with a code-signing certificate.
* Windows Firewall asks once to allow Basil BACnet Explorer on the network – allow **Private** networks
  (and Public if you commission on public-profile networks).
