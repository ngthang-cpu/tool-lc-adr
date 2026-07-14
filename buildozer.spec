[app]
title = LC79 Thong Ke
package.name = lc79thongke
package.domain = vn.nguyentungthang
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,txt,md
source.exclude_dirs = tests,.git,.github,.venv,__pycache__
version = 1.0.0
requirements = python3,kivy==2.3.1,requests,urllib3,certifi
presplash.filename = %(source.dir)s/presplash.png
icon.filename = %(source.dir)s/icon.png
orientation = portrait
fullscreen = 0

android.permissions = INTERNET,WAKE_LOCK
android.api = 35
android.minapi = 23
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.logcat_filters = *:S python:D

[buildozer]
log_level = 2
warn_on_root = 1
