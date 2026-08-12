[app]
title = CodexSessionManager
project_dir = .
input_file = app_entry.py
exec_directory = dist
project_file =
icon = build/CodexSessionManager.ico

[python]
python_path = build/.venv-build/Scripts/python.exe
packages = Nuitka==4.0
android_packages = buildozer==1.5.0,cython==0.29.33

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Svg,Widgets
plugins = platforms,imageformats,iconengines,styles,tls

[android]
wheel_pyside =
wheel_shiboken =
plugins =

[nuitka]
macos.permissions =
mode = standalone
extra_args = --quiet --report=build/nuitka-compilation-report-windows.xml --assume-yes-for-downloads --windows-console-mode=attach --windows-file-version=1.0.0.0 --windows-product-version=1.0.0.0 --windows-product-name=CodexSessionManager --windows-file-description=CodexSessionManager --include-package=ijson --include-package=rich._unicode_data --include-package-data=qtvscodestyle --include-package-data=codex_session_manager --nofollow-import-to=mypy.* --nofollow-import-to=pytest.* --nofollow-import-to=_pytest.* --nofollow-import-to=ruff.* --nofollow-import-to=nuitka.*

[buildozer]
mode = debug
recipe_dir =
jars_dir =
ndk_path =
sdk_path =
local_libs =
arch =
