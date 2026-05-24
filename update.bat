@echo off
:: 设置命令提示符使用 UTF-8 编码，彻底解决中文乱码
chcp 65001 >nul

echo ====================================
echo 正在准备一键同步代码到 GitHub...
echo ====================================

:: 1. 添加所有更改
git add .

:: 2. 提示输入更新说明
set /p msg="请输入这次更新的说明 (直接回车默认为 'Auto update'): "
if "%msg%"=="" set msg=Auto update

:: 3. 提交更改
git commit -m "%msg%"

:: 4. 推送到云端
echo 正在推送到 GitHub...
git push origin main

echo ====================================
echo 更新完成！
echo ====================================
pause