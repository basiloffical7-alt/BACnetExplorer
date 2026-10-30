[app]
title = Basil BACnet
package.name = basilbacnet
package.domain = com.basil
source.dir = .
source.include_exts = py,png,json
source.exclude_dirs = tests, bin, .buildozer, __pycache__
version = 1.0.0
requirements = python3,kivy==2.3.1,pyjnius,android,androidstorage4kivy
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #FFFFFF
orientation = portrait, landscape
fullscreen = 0

# BACnet/IP needs the network; Wi-Fi multicast state lets the app receive broadcast I-Am replies
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_MULTICAST_STATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 0
