@echo off
:: 使い方: install.bat [プロキシURL]
:: 例:    install.bat http://proxy.example.com:8080
if "%1"=="" (
    pip install -r requirements.txt
) else (
    pip install --proxy %1 -r requirements.txt
)
pause
