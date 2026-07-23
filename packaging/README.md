# Packaging

这里保留 PyInstaller 和 Inno Setup 配置文件。

项目不保存固定打包脚本；需要打包指定版本时，使用一次性命令传入输出文件名和图标路径。

## 依赖

- Python 依赖已通过根目录 `requirements.txt` 安装
- [Inno Setup 6](https://jrsoftware.org/isdl.php)
- `third_party/presentmon/PresentMon.exe` 为官方 PresentMon 2.4.1 x64 控制台程序，SHA-256 记录在同目录 `README.md`
- `languages/ChineseSimplified.isl` 为 Inno Setup 官方源码仓库提供的简体中文语言资源

## 生成安装包

在项目根目录运行以下 PowerShell 命令，并按发布版本修改 `$version`：

```powershell
$version = "2.5.2"

python -c "from pathlib import Path; from PIL import Image; Path('build').mkdir(exist_ok=True); image=Image.open('vrctool_app/assets/logo.png').convert('RGBA'); image.save('build/logo.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"

$env:VRCTOOL_EXE_NAME = "vrctool"
$env:VRCTOOL_BUNDLE_NAME = "vrctool_v$version"
$env:VRCTOOL_ICON_PATH = (Resolve-Path "build\logo.ico").Path
python -m PyInstaller --noconfirm --clean --workpath build\pyinstaller --distpath build\package packaging\vrctool.spec

$env:VRCTOOL_VERSION = $version
$iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc packaging\vrctool.iss
```

最终输出文件：

```text
dist\vrctool-setup-2.5.2.exe
```

PyInstaller 生成的目录包仅位于 `build\package\vrctool_v2.5.2`，作为 Inno Setup 的临时输入，不作为发布文件。程序安装后直接从安装目录加载依赖，不会像单文件 EXE 一样每次启动都解压到临时目录。`third_party/presentmon` 会放入目录包的 `_internal` 运行内容中；Inno Setup 还会将 `PresentMon.exe` 安装到 `{app}\tools`，并将 MIT 许可证安装到 `{app}\licenses`，安装版优先使用外层工具目录。

安装器首屏可切换“简体中文”和 English，默认优先使用简体中文。

## 发布更新

1. 将代码版本号和 `$version` 设为相同值。
2. 创建格式为 `vrctool_v2.5.2` 的 Git 标签和 GitHub Release。
3. 上传 `vrctool-setup-2.5.2.exe`。安装版会读取 GitHub Release 的 SHA-256 摘要并校验下载文件。
4. 只上传 `vrctool-setup-2.5.2.exe`；网页更新和 `vrctool upgrade` 都只下载并运行此安装包。

正式公开分发前，建议使用 Authenticode 证书同时签名应用 EXE 和安装包。

安装器会将 `%LOCALAPPDATA%\Programs\vrctool` 添加到当前用户的 `PATH`，因此新打开的终端可以直接执行 `vrctool`。卸载时只移除这一条路径。

用户可通过 `vrctool uninstall`、Windows“设置”或安装目录中的 Inno Setup 默认卸载程序 `unins000.exe` 卸载。

静默部署时可附加 `/NOLAUNCH`，阻止安装完成后自动启动应用。

自动化卸载可使用 `vrctool uninstall --silent`。
