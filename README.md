# vrctool

一个网页形式运行的 VRChat OSC 工具，集成 ChatBox 文本发送、硬件信息发送、挂机计时、实时游戏帧率、DG-LAB 郊狼 3.0 WebSocket 联动和自定义 OSC 映射。

## 界面预览

| 总览                              | 心率广播                                |
| --------------------------------- | --------------------------------------- |
| ![总览](docs/images/overview.png) | ![心率广播](docs/images/heart-rate.png) |

| 郊狼控制                           | OSC 映射                                 |
| ---------------------------------- | ---------------------------------------- |
| ![郊狼控制](docs/images/dglab.png) | ![OSC 映射](docs/images/osc-mapping.png) |

## 功能

- ChatBox 自定义文本循环发送：单独开启时立即发送，并每 3 秒刷新一次。
- ChatBox 硬件信息发送：CPU、GPU、显存、内存信息。
- ChatBox 挂机计时发送。
- ChatBox 批量轮播：同时开启多个广播功能时，按照固定顺序逐项发送，避免各功能抢占聊天框。
- 心率广播：扫描支持标准蓝牙 Heart Rate Service 的手表/心率带，实时读取 BPM 并发送到 VRChat ChatBox。
- 游戏帧率广播：使用 PresentMon 采集 `VRChat.exe` 的呈现事件，显示实时 FPS、5 秒平均 FPS 和帧时间，并发送到 ChatBox。
- DG-LAB 郊狼 3.0 WebSocket 连接：网页按钮弹出二维码，设备连接后自动切换为取消连接。
- DG-LAB A/B 通道强度、波形、上限、面板模式、交互模式控制。
- DG-LAB 状态发送到 VRChat ChatBox，状态更新时间为 1 秒。
- OSC 映射：支持默认 A/B 参数，也支持自定义 OSC 参数。
- 自定义 OSC 参数可选择 A、B、A+B 通道，并可用勾选框控制是否生效。
- 配置自动保存到 `config.json`，重启后继续生效。
- 启动器带单实例保护，重复打开时不会再启动第二套后端组件。
- 控制台式网页界面：左侧分区导航和基础设置弹窗，右侧任务工作区，支持浅色/深色主题切换。
- 郊狼强度环形可视化，会随 A/B 通道强度实时变化。

## v2.3.2 更新内容

- 新增 `游戏帧率` 页面和 VRChat 实时 FPS ChatBox 广播。
- 使用 PresentMon 按 `VRChat.exe` PID 采集 Windows 呈现事件，不读取游戏内存、不注入游戏，也不使用 CPU/GPU 利用率估算 FPS。
- 自动检测 VRChat 启动、关闭和重启，并在新进程出现后重新绑定采集器。
- 支持当前 FPS、最近 5 秒平均 FPS、帧时间、低 FPS 阈值与网页告警。
- 广播默认每 3 秒发送，启用或恢复采样后立即发送一次；用开关按钮选择广播 `当前 FPS`（常开）、`平均 FPS`、`帧时间`。
- 新增 ChatBox 批量轮播：同时开启多个广播功能时，按“自定义文字 -> 设备信息 -> 挂机计时 -> 心率 -> 游戏帧率 -> 郊狼状态”依次发送，避免抢占聊天框。
- 安装版改为目录包架构，依赖在安装时展开到程序目录，启动时不再重复解压单文件程序；应用内更新仍使用安装包覆盖升级并保留用户配置。
- 安装包包含 PresentMon 2.4.1，关闭 vrctool 时会清理监控任务和采集进程。
- 新增命令行更新：`vrctool upgrade` 与 `vrctool -u` 可检查、下载、校验并安装新版本。
- 网页端口写入本地配置，支持命令行和网页“基础设置”弹窗修改；启动前会检测端口占用，避免后端组件半启动。
- `vrctool -p <端口>` / `vrctool setport <端口>` 只保存默认端口，`vrctool start -p <端口>` 仅本次临时使用指定端口。
- 新版本首次启动时自动显示本地更新内容；勾选“不再提醒”后当前版本不再弹出，下一版本会自动恢复提醒。

## 环境

- Windows 10/11
- 安装版不需要 Python；从源码运行需要 Python 3.10 或更高版本
- VRChat 已开启 OSC
- 如需郊狼联动，需要 DG-LAB App 和郊狼 3.0 设备
- 如需心率广播，需要手表或心率带开启蓝牙心率广播模式
- 游戏帧率采集需要管理员权限，或当前 Windows 用户属于 `Performance Log Users` 组

## 安装

### 使用安装包（推荐）

[GitHub Releases](https://github.com/danglong0313/vrctool/releases) 只提供 Windows 安装包：

| 文件名                      | 用途                                                             |
| --------------------------- | ---------------------------------------------------------------- |
| `vrctool-setup-2.3.2.exe` | 安装包，会创建安装记录、快捷方式并配置命令行。 |

安装步骤：

1. 从 [GitHub Releases](https://github.com/danglong0313/vrctool/releases) 下载 `vrctool-setup-2.3.2.exe`。
2. 双击安装包；首屏可在“简体中文”和 English 之间切换。
3. 按照提示完成安装，不需要管理员权限。
4. 从开始菜单或桌面快捷方式启动 vrctool。
5. 如需使用命令行，请在安装完成后重新打开 PowerShell 或命令提示符。

当前安装包尚未进行代码签名，Windows SmartScreen 可能显示“未知发布者”。请确认安装包来自本项目的 GitHub Releases。

### 默认安装路径

默认程序目录为：

```text
%LOCALAPPDATA%\Programs\vrctool
```

展开后的路径通常是：

```text
C:\Users\<用户名>\AppData\Local\Programs\vrctool
```

安装完成后主要文件位置如下：

| 内容         | 默认路径                                         |
| ------------ | ------------------------------------------------ |
| 程序目录     | `%LOCALAPPDATA%\Programs\vrctool`              |
| 主程序       | `%LOCALAPPDATA%\Programs\vrctool\vrctool.exe`  |
| 运行依赖目录 | `%LOCALAPPDATA%\Programs\vrctool\_internal`    |
| 帧率采集器   | `%LOCALAPPDATA%\Programs\vrctool\tools\PresentMon.exe` |
| PresentMon 许可 | `%LOCALAPPDATA%\Programs\vrctool\licenses\PresentMon-LICENSE.txt` |
| 默认卸载程序 | `%LOCALAPPDATA%\Programs\vrctool\unins000.exe` |
| 用户配置     | `%LOCALAPPDATA%\vrctool\config.json`           |

程序文件和用户配置分开保存，因此覆盖安装和应用内更新会保留配置，卸载应用时默认也会保留用户配置。

### 从源码运行

安装包用户不需要安装 Python。从源码运行或自行打包时，先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 启动

安装版可以从开始菜单、桌面快捷方式或命令行启动：

```powershell
vrctool start
```

从源码运行时，双击 `run.bat`，或在 PowerShell 中运行：

```powershell
.\run.ps1
```

启动后会自动打开网页：

```text
http://127.0.0.1:8765
```

### Windows 命令行

安装完成后重新打开 PowerShell 或命令提示符，即可直接使用 `vrctool` 命令：

```powershell
vrctool start
vrctool version
vrctool -v
vrctool -p 8877
vrctool setport 8877
vrctool start -p 8877
vrctool upgrade
vrctool -u
vrctool upgrade --check
vrctool uninstall
```

- `start`：使用配置文件中的默认网页端口启动应用，省略命令时也会启动。
- `version` / `-v`：显示当前版本号。
- `-p <端口>` / `setport <端口>`：保存默认网页端口并退出，不启动应用。
- `start -p <端口>`：仅本次使用指定端口启动，不写入配置文件。
- `upgrade` / `-u`：检查新版本，下载安装包，通过 SHA-256 校验后启动覆盖更新。
- `upgrade --check`：只检查是否存在新版本，不下载或安装。
- `uninstall`：关闭正在运行的 vrctool，并启动卸载程序。

启动器会在加载 OSC、DG-LAB 等组件前检测网页端口。端口被占用时会停止启动并显示可直接执行的换端口命令。

网页左侧的“基础设置”按钮会打开设置弹窗，可修改默认网页端口、ChatBox 地址与发送间隔。网页端口保存后在下次启动生效，弹窗会分别显示当前运行端口和下次启动端口。

安装目录中也提供可直接双击的卸载入口：

```text
%LOCALAPPDATA%\Programs\vrctool\unins000.exe
```

这是 Inno Setup 默认生成的卸载程序文件名；平时推荐直接使用 `vrctool uninstall` 或 Windows“设置”中的卸载入口。

## 关闭

推荐直接关闭启动窗口，或在启动窗口按 `Ctrl+C`。

后端服务运行在启动器同一个进程里，窗口关闭时后端会一起退出，不会留下隐藏的 uvicorn 进程。

网页左侧也有关闭按钮，用它会请求启动器关闭后端服务。

## 应用更新

安装版会在启动后检查 GitHub Releases，也可以在网页左侧的 `应用更新` 区域或命令行中手动检查。

发现新版本后，可以直接下载安装包。下载完成并通过 SHA-256 校验后，点击 `安装并重启`，当前服务会正常退出，安装器覆盖旧版本并重新启动应用。

更新到新版本后，启动时会自动显示该版本的更新内容。直接关闭且不勾选时，本次运行不再重复弹出，但下次启动仍会显示；勾选“不再提醒”后，配置文件会记录当前版本号，同一版本以后不再弹出。安装下一版本时版本号自动失配，因此无需手动清除设置即可恢复提醒。

源码运行模式可以查看新版本，但不会自动安装。

命令行更新示例：

```powershell
vrctool upgrade --check
vrctool upgrade
```

## VRChat 设置

在 VRChat 中确认 OSC 已开启：

```text
Options -> OSC -> Enabled
```

默认监听：

```text
127.0.0.1:9001
```

ChatBox 默认发送到：

```text
127.0.0.1:9000
```

## ChatBox 批量轮播

`ChatBox` 分区中的批量轮播默认开启。只开启一个广播功能时，该功能仍按自己的间隔直接发送；同时开启两个或更多功能后，vrctool 会按以下顺序每次只发送一项：

```text
自定义文字 -> 设备信息 -> 挂机计时 -> 心率 -> 游戏帧率 -> 郊狼状态
```

未开启或暂时没有有效内容的项目会自动跳过，同一项目尚未发送的旧内容会被最新状态替换。网页可调整全局“每项间隔”，并查看当前发送项和下一项。关闭批量轮播后，各功能恢复独立发送。

## DG-LAB 连接

1. 在网页 DG-LAB 分区选择扫码 IP 和 WS 端口。
2. 点击 `连接设备`。
3. 在弹窗中用 DG-LAB App 扫描二维码。
4. 连接成功后按钮会变成 `取消连接`。

强度上限会按照设备 WebSocket 返回的最大值限制，网页设置不会超过设备返回上限。

## 心率广播

1. 在手表或心率带上开启心率广播模式。
2. 打开网页 `心率广播` 分区。
3. 点击 `扫描设备`，选择你的心率设备。
4. 点击 `连接设备`，看到 BPM 后点击 `发送到 ChatBox`。

默认每 1 秒发送一次心率到 VRChat ChatBox，可在网页中调整发送间隔。该功能使用标准蓝牙 Heart Rate Service；如果设备没有开放标准心率服务，可能无法读取。

## 游戏帧率广播

1. 启动 VRChat 和 vrctool。
2. 打开网页 `游戏帧率` 分区。
3. 等待状态变为 `采样中`，确认页面出现 FPS 和帧时间。
4. 设置发送间隔、低 FPS 阈值，并用 `广播内容` 的开关按钮选择要发送的指标。
5. 打开 `广播开关`。有有效采样时会立即发送一次，之后按设置间隔发送。

`广播内容` 用开关按钮控制消息里包含哪些指标：`当前 FPS` 为常开项，无法关闭；`平均 FPS`、`帧时间` 可自由开关，点击即时生效。默认只开 `当前 FPS` 和 `帧时间`：

```text
FPS: 72.3 | Frame: 13.9ms
```

三项全开时的消息形如 `FPS: 72.3 | AVG: 69.0 | Frame: 13.9ms`。采样与 ChatBox 广播分别运行，PresentMon 会持续更新网页，但不会每帧发送消息。批量轮播且同时启用其他广播时，帧率消息会进入统一轮播。VRChat 关闭或帧数据失效后会自动停发；VRChat 重新启动后，vrctool 会绑定新的 PID 并恢复采样和广播。

该功能使用 [Intel PresentMon](https://github.com/GameTechDev/PresentMon) 2.4.1 的 Windows ETW 呈现事件，不读取 VRChat 内存、不向游戏注入代码，也不依赖 VRChat OSC 获取 FPS。PresentMon 启动 ETW 会话需要以下任一条件：

- 右键选择“以管理员身份运行”启动 vrctool；或
- 将当前 Windows 用户加入 `Performance Log Users` 组，注销并重新登录后再启动 vrctool。

权限不足、VRChat 未运行、没有捕获到呈现帧或 PresentMon 异常退出时，网页会显示具体原因并停止发送。VRChat 可能存在桌面镜像和头显等多个交换链，vrctool 会选择最近窗口内帧数最多的活跃交换链，避免重复累加；显示值表示 `VRChat.exe` 的应用呈现速率，可能与 VR 运行时重投影后的头显显示频率不同。

## OSC 映射

默认提供两条常用参数：

```text
/avatar/parameters/DG-LAB/UpperLeg_L
/avatar/parameters/DG-LAB/UpperLeg_R
```

这两条参数不固定绑定 A/B，可以在网页中分别选择目标通道 `A`、`B` 或 `A+B`。也可以继续添加自定义 OSC 参数，每条自定义参数都有 `生效` 勾选框，取消勾选后该参数不会触发郊狼强度。

## 配置文件

源码运行后会在项目目录生成：

```text
config.json
```

安装版的配置保存在：

```text
%LOCALAPPDATA%\vrctool\config.json
```

这个文件在 `app.web_port` 中保存默认网页端口，在 `app.dismissed_release_notes_version` 中保存已关闭提醒的版本号，同时保存 OSC 映射、DG-LAB 设置、ChatBox 文本、批量轮播开关和间隔、心率设备地址、帧率广播开关、发送间隔、阈值和广播指标开关等本地配置。配置与程序文件分开保存，覆盖升级时会继续保留。它是本机配置文件，不会提交到 Git 仓库。

## 打包 EXE

项目不保留固定的 `build_exe.bat` 或 `build_exe.ps1` 打包脚本。

需要打包时按照 [packaging/README.md](packaging/README.md) 执行一次性 PyInstaller 和 Inno Setup 命令，最终只输出安装包：

```text
dist\vrctool-setup-2.3.2.exe
```

目录包中的 `_internal` 是安装器的临时构建内容，不单独发布；安装器会自动将其放入默认程序目录。应用内更新只下载并运行 `setup` 安装包，更新时会替换旧 `_internal` 内容，用户配置仍保存在 `%LOCALAPPDATA%\vrctool\config.json`。安装器首屏支持“简体中文”和 English 切换。

`vrctool_app/assets/logo.png` 会作为网页 Logo，也会在打包时转换为 exe 图标。

默认打包为控制台 exe。关闭 exe 窗口时，后端服务会一起关闭。

## 项目结构

```text
vrctool_app/
  launcher.py           启动器，负责窗口生命周期和打开网页
  server.py             FastAPI 后端接口
  single_instance.py    防止多开导致组件冲突
  installation.py       查找并启动 Windows 卸载程序
  config_store.py       用户配置路径和旧配置迁移
  chatbox.py            ChatBox 文本、设备信息、挂机计时和统一轮播
  dglab.py              DG-LAB WebSocket、强度、波形和二维码连接
  heartrate.py          蓝牙心率读取和 ChatBox 广播
  performance.py        VRChat 进程检测、PresentMon 采样、FPS 统计和广播
  osc.py                VRChat OSC 监听和映射
  update_manager.py     GitHub Release 检查、下载和更新安装
  release_notes.py      当前版本更新内容和按版本提醒判断
  assets/               Logo 等资源
  web/                  网页前端
packaging/              PyInstaller 和 Inno Setup 打包配置
third_party/presentmon/ PresentMon 2.4.1 x64 与 MIT 许可证
tests/                  命令行、安装、配置迁移、帧率采集和应用更新自动测试
references/legacy/      早期参考脚本
docs/images/            README 界面截图
requirements.txt        Python 依赖
run.bat / run.ps1       本地启动入口
```

## 开源项目致谢

感谢开源项目 [ccvrc/DG-LAB-VRCOSC](https://github.com/ccvrc/DG-LAB-VRCOSC) 为本项目的开发提供参考。

感谢 [Intel PresentMon](https://github.com/GameTechDev/PresentMon) 提供 Windows 显示呈现事件采集能力。本项目随安装包分发未修改的 PresentMon 2.4.1 x64 二进制，其 MIT 许可证保存在 `third_party/presentmon/LICENSE.txt`。
