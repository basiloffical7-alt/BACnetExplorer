# Basil BACnet for Android – getting the APK

The APK is built for free in GitHub's cloud (Google's Android build tools run there).
You need a GitHub account (free) and about 30 minutes the first time.

## 1. Put the project on GitHub
1. Sign in at https://github.com, click **+ ▸ New repository**, name it `basil-bacnet`, choose **Private**, click **Create**.
2. On the new repository page click **uploading an existing file**.
3. Unzip `BasilBACnetExplorer.zip` on your PC, open the `BACnetExplorer` folder, and drag **everything inside it**
   (including the hidden `.github` folder – on Windows enable *View ▸ Hidden items*) into the browser.
4. Click **Commit changes**.

## 2. Build
1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Select **Build Android APK** ▸ **Run workflow** ▸ **Run workflow**.
3. Wait until the run shows a green tick (the first build takes 20–40 min; later builds about 10 min).

## 3. Install on the phone
1. Open the finished run and download **BasilBACnet-apk** (a zip containing `basilbacnet-1.0.0-...-debug.apk`).
2. Copy the `.apk` to your phone (USB, WhatsApp to yourself, Google Drive …) and tap it.
3. Allow **Install unknown apps** for the app you opened it with, then tap **Install**.
   (Play Protect may warn because the app isn't from the Play Store – choose **Install anyway**.)

`BasilBACnet-screenshots` from the same run shows each screen of the app running against the BACnet simulator.

## Using it
* Log in: **admin / Basil@12345** (tick *Keep me signed in* for auto login).
* The phone must be on the **same Wi-Fi/LAN** as the BACnet devices (or use a BBMD in *Settings ▸ Network*).
* Tabs: **Devices** (Discover, + IP), **Watch** (live list, flashes on change), **Graphics**, **Report** (Excel + Share), **Settings**.
* Tap a value to write it; tap **+** to add a point to Watch; tap a name to open all its properties and the priority array.
* Not on Android: changing the PC's IP address (Android doesn't allow apps to change the Wi-Fi IP).
