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
# 64-bit phones (all phones from ~2017 on). Building two archs at once corrupts p4a's pip.
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = apk
# python-for-android 'develop' pinned to a fixed commit (2026-10-27): its pip step installs
# Android wheels correctly (the v2026.05.09 release fails on charset_normalizer)
p4a.branch = develop
p4a.commit = 1c9a4b4f817847bd8505d972d1a0e6f965929a88

[buildozer]
log_level = 2
warn_on_root = 0
