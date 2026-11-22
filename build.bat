@echo off
python -m PyInstaller ^
    --onefile ^
    --noconsole ^
    --name batteryChecker ^
    main.py