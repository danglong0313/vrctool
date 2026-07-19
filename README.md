# vrctool

一个网页形式运行的 VRChat OSC 工具，集成 ChatBox 文本发送、硬件信息发送、挂机计时、实时游戏帧率、正在播放、当前天气、DG-LAB 郊狼 3.0 WebSocket 联动和自定义 OSC 映射。

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
- ChatBox 批量轮播：按固定顺序为广播功能分配时间片，并在各自时间片内按功能自己的发送间隔持续更新，避免互相抢占聊天框。
- 心率广播：扫描支持标准蓝牙 Heart Rate Service 的手表/心率带，实时读取 BPM 并发送到 VRChat ChatBox。
- 游戏帧率广播：使用 PresentMon 采集 `VRChat.exe` 的呈现事件，显示实时 FPS、5 秒平均 FPS 和帧时间，并发送到 ChatBox。
- 正在播放广播：通过 Windows 媒体会话读取 QQ 音乐或网易云音乐的歌曲信息；QQ 音乐还可按歌曲比例显示播放进度，并发送到 ChatBox 第二行。
- 天气广播：自动识别用户当前城市和实时天气，显示温度、体感温度、湿度、风速与降水，并定时发送到 ChatBox。
- DG-LAB 郊狼 3.0 WebSocket 连接：网页按钮弹出二维码，设备连接后自动切换为取消连接。
- DG-LAB A/B 通道强度、波形、上限、面板模式、交互模式控制。
- DG-LAB 状态发送到 VRChat ChatBox，状态更新时间为 1 秒。
- OSC 映射：支持默认 A/B 参数，也支持自定义 OSC 参数。
- 自定义 OSC 参数可选择 A、B、A+B 通道，并可用勾选框控制是否生效。
- 配置自动保存到 `config.json`，重启后继续生效。
- 启动器带单实例保护，重复打开时不会再启动第二套后端组件。
- 控制台式网页界面：左侧分区导航和基础设置弹窗，右侧任务工作区，支持浅色/深色主题切换。
- 郊狼强度环形可视化，会随 A/B 通道强度实时变化。

## v2.5.0 更新内容

- 新增 `正在播放` 页面，通过 Windows 媒体会话识别 QQ 音乐与网易云音乐的歌名、歌手、专辑和播放器。
- 正在播放信息接入 ChatBox 独立广播与批量轮播，消息固定以 `正在播放:` 开头。
- 原消息模板改为 `歌名`、`歌手`、`专辑`、`播放器`、`进度` 五个开关，并兼容迁移旧配置。
- 播放进度按“当前时间 / 总时长”的比例移动，并在 ChatBox 第二行显示，例如 `0:10 ->----- 1:00`。
- QQ 音乐可以通过 Windows 媒体会话返回播放进度；网易云音乐官方客户端不支持返回有效进度时间轴，因此网易云只显示歌曲信息，不发送虚假进度。
- 播放器暂停、退出或缺少有效歌名时自动退出轮播，恢复播放后自动重新加入。

## v2.4.4 更新内容

- 这是 v2.4.3 的后续稳定性补丁。
- ChatBox 批量轮播改为时间片模式：轮到某个功能后，在全局“每项轮播时长”内按该功能自己的发送间隔持续更新，到时才切换下一项。
- 设备信息在每次实际发送前重新采样；心率、挂机、游戏帧率和郊狼状态会按各自间隔使用发送时的最新值，不再只显示进入轮播时的固定文本。
- 天气广播在外部服务临时失败时保留上一次有效数据并继续轮播，后台异常不会终止后续刷新；更换地点时会清除旧地点数据。
- 游戏帧率统计改用 PresentMon 事件时间，优先选择最近仍活跃的交换链，降低延迟批量输出、旧交换链和多交换链造成的误差。
- 修复 ChatBox 批量任务在关闭时可能延迟退出的问题，并补充时间片连续发送、天气重试和帧率统计测试。

## v2.4.3 更新内容

- 这是 v2.4.2 的后续稳定性补丁。
- 天气广播会保留最新消息并持续加入 ChatBox 批量轮播，下一次天气更新会自动替换旧内容。
- 修复 DG-LAB 连接变化时第三方心跳任务可能退出，导致重连后断线越来越频繁的问题。
- DG-LAB 心跳发送改为连接快照处理，单个连接失败不会终止整个心跳循环。
- 服务停止或重新连接时会等待旧心跳任务完整退出，并提高短暂网络抖动的容忍度。
- 郊狼 App 断线后立即清理旧绑定、连接计数和强度状态，等待 App 干净地重新绑定。
- 新增天气持续轮播、心跳异常、连接变化、重复重连和资源清理测试。

## v2.4.2 更新内容

- 这是 v2.4.1 的后续补丁更新，修复中国大陆网络访问天气服务时可能返回 403 的问题。
- Open-Meteo 不可用时自动切换 UAPI 国内备用天气源；国内 IP 定位与行政区解析也会优先使用国内接口。
- 天气地点补全为地级市与区县，例如“北京市朝阳区”，国内服务不可用时仍会继续使用原有国际服务回退。
- 天气页面显示当前实际使用的数据源，并支持通过环境变量替换为自建镜像地址。
- 启动器改为等待网页服务完全就绪后再打开浏览器，避免启动较慢时先弹出“拒绝连接”。

## v2.4.1 更新内容

- 修复浏览器定位后城市显示成“当前位置天气”的问题。
- 浏览器坐标现在会反向解析为真实城市名，并在本次运行中缓存解析结果。
- 无法识别城市时不显示占位地点、不保留旧天气数据，也不发送 ChatBox 天气消息。
- IP 定位和手动城市搜索同样只接受有效城市名。

## v2.4.0 更新内容

- 新增 `天气` 页面，显示当前位置、天气状况、温度、体感温度、湿度、风速和降水。
- 优先使用浏览器位置权限自动定位并反向解析城市名；定位不可用时回退到 IP 城市估算，也支持手动搜索城市。
- 新增天气 ChatBox 广播，默认每 10 分钟更新，可在 5 到 60 分钟之间调整。
- 天气消息接入 ChatBox 批量轮播，每次天气更新只发送一次，不会按轮播间隔重复发送旧天气。
- 批量轮播顺序更新为“自定义文字 -> 设备信息 -> 挂机计时 -> 心率 -> 游戏帧率 -> 天气 -> 郊狼状态”。
- 天气广播开关和间隔会自动保存；精确坐标只保留在当前运行状态，不写入配置文件。
- 只有识别到真实城市名后才显示和发送天气；识别失败会清空旧地点与天气数据。
- 新增天气定位、数据解析、消息格式、广播任务清理与一次性轮播测试。

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
| `vrctool-setup-2.5.0.exe` | 安装包，会创建安装记录、快捷方式并配置命令行。 |

安装步骤：

1. 从 [GitHub Releases](https://github.com/danglong0313/vrctool/releases) 下载 `vrctool-setup-2.5.0.exe`。
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

`ChatBox` 分区中的批量轮播默认开启。只要开启了一个或多个广播功能，vrctool 就会按照全局“每项轮播时长”为每个功能分配独占时间片；开启多个功能时按以下顺序切换：

```text
自定义文字 -> 设备信息 -> 挂机计时 -> 心率 -> 游戏帧率 -> 正在播放 -> 天气 -> 郊狼状态
```

未开启或暂时没有有效内容的项目会自动跳过。轮到某个功能时会立即发送一次，并在该时间片内继续按照该功能自己的发送间隔生成和发送实时文本，时间片结束后才切换到下一项。例如“每项轮播时长”为 5 秒、心率发送间隔为 1 秒时，心率会在自己的 5 秒时间片内约每秒更新，而不是 5 秒只显示一个固定值。设备信息会在每次实际发送前重新采样；挂机计时、心率、游戏帧率和郊狼状态也会读取发送时的最新运行状态。

网页可调整全局“每项轮播时长”，并查看当前发送项和下一项。关闭批量轮播后，各功能恢复完全独立发送。

天气广播会在每次更新后替换轮播中的天气内容，并保留最新一条消息持续参与轮播；关闭天气广播后会立即从轮播中移除。

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

三项全开时的消息形如 `FPS: 72.3 | AVG: 69.0 | Frame: 13.9ms`。采样与 ChatBox 广播分别运行，PresentMon 会持续更新网页，但不会每帧发送消息。批量轮播开启时，帧率在自己的时间片内按照帧率广播间隔发送，每次都根据最新采样重新生成文本。VRChat 关闭或帧数据失效后会自动停发；VRChat 重新启动后，vrctool 会绑定新的 PID 并恢复采样和广播。

该功能使用 [Intel PresentMon](https://github.com/GameTechDev/PresentMon) 2.4.1 的 Windows ETW 呈现事件，不读取 VRChat 内存、不向游戏注入代码，也不依赖 VRChat OSC 获取 FPS。PresentMon 启动 ETW 会话需要以下任一条件：

- 右键选择“以管理员身份运行”启动 vrctool；或
- 将当前 Windows 用户加入 `Performance Log Users` 组，注销并重新登录后再启动 vrctool。

权限不足、VRChat 未运行、没有捕获到呈现帧或 PresentMon 异常退出时，网页会显示具体原因并停止发送。统计窗口使用 PresentMon 事件自身的 `TimeInSeconds`，不会把延迟后批量输出的旧帧误算成同一秒的新帧。VRChat 可能存在桌面镜像和头显等多个交换链，vrctool 会从最近仍在呈现的交换链中选择当前帧数最多的一条，避免旧交换链或多个交换链重复影响结果；显示值表示 `VRChat.exe` 的应用呈现速率，可能与 VR 运行时重投影后的头显显示频率不同。

## 正在播放广播

1. 打开 QQ 音乐或网易云音乐并开始播放歌曲。
2. 打开网页 `正在播放` 分区，确认页面显示播放器、歌名和歌手。
3. `自动选择` 会优先使用当前处于播放状态的受支持播放器，也可以固定为 QQ 音乐或网易云音乐。
4. 根据需要调整发送间隔，并使用 `歌名`、`歌手`、`专辑`、`播放器`、`进度` 五个按钮选择广播内容，然后打开 `ChatBox 广播`。

默认开启歌名、歌手和进度。进度条会在 ChatBox 第二行显示，箭头随播放位置移动：

```text
正在播放: ♪ 往事越千年 | 歌手: Alger
0:10 ->----- 1:00
```

`歌名` 表示当前歌曲标题，`歌手` 表示演唱者，`专辑` 表示歌曲所属专辑，`播放器` 表示 QQ 音乐或网易云音乐，`进度` 表示当前播放时间、文本进度条和歌曲总时长。消息会固定以 `正在播放:` 开头，并且至少需要保留一项广播内容。QQ 音乐可以通过 Windows 媒体会话返回有效播放位置和总时长，因此能够显示随歌曲比例移动的进度条。网易云音乐官方客户端不支持返回有效进度时间轴，所以网易云只显示歌名等歌曲信息；网页会明确提示该限制，ChatBox 不会发送虚假的固定进度。播放器暂停、退出或没有提供有效歌名时，正在播放来源会自动退出 ChatBox 轮播；恢复播放后会自动重新加入。该功能每秒检查一次 Windows 媒体会话，但只按页面设置的发送间隔向 ChatBox 广播，不会每次检测都发送。

当前版本仅识别 QQ 音乐与网易云音乐的 Windows 媒体会话。播放器必须向 Windows 系统媒体控制中心公开播放信息；若页面一直显示等待播放，请先确认 Windows 音量面板或媒体快捷面板能显示该应用的歌曲信息。不同播放器版本可能使用不同的媒体会话标识，可通过页面显示与日志进一步确认适配情况。

歌曲信息只在本机读取，不上传到第三方服务；广播默认关闭，只有用户主动开启后才会发送到 VRChat。

## 天气广播

1. 打开网页 `天气` 分区。
2. 浏览器会请求位置权限；允许后会将设备坐标反向解析为“地级市 + 区/县”，例如 `北京市朝阳区`，再查询天气。
3. 若拒绝授权或浏览器定位不可用，vrctool 会自动改用 IP 估算位置。也可以在输入框中搜索城市手动修正。
4. 确认页面中的位置和天气后，打开 `ChatBox 广播` 并设置更新间隔。

天气广播默认关闭，天气数据默认每 10 分钟刷新一次，可在 5 到 60 分钟之间调整。批量轮播开启后，每次轮到天气时间片都会发送当前最新天气；下一次天气更新后会自动改用新内容。天气的分钟间隔是外部数据刷新间隔，不会在几秒的时间片内反复请求天气服务。关闭批量轮播后，天气按自己的数据刷新间隔独立发送。

天气主数据源为 [Open-Meteo](https://open-meteo.com/)。国内网络出现 `403`、超时或无效响应时，程序会自动切换到 [UAPI 国内备用天气源](https://uapis.cn/docs/api-reference/get-misc-weather)；国内 IP 定位和省/市/区县解析也优先使用 UAPI 的国内接口，失败后再回退到 [ipapi](https://ipapi.co/) 和 [OpenStreetMap Nominatim](https://nominatim.org/release-docs/develop/api/Reverse/)。这些默认接口均不需要用户填写 API Key，也可通过 `VRCTOOL_DOMESTIC_WEATHER_URL`、`VRCTOOL_DOMESTIC_DISTRICT_URL`、`VRCTOOL_DOMESTIC_IP_LOCATION_URL` 和 `VRCTOOL_REVERSE_GEOCODING_URL` 环境变量替换为自建镜像。

城市解析只在定位或手动搜索时执行，不会随天气刷新重复请求；浏览器定位坐标不写入配置文件，配置文件只保存天气广播开关和间隔。使用 OpenStreetMap 回退时，城市数据遵循其 [ODbL 许可与署名要求](https://www.openstreetmap.org/copyright)。网页会显示本次天气使用的实际数据源。

IP 定位只能估算城市，使用 VPN、代理、移动网络或运营商异地出口时可能显示错误地点。遇到这种情况，请点击 `自动定位` 并允许浏览器位置权限，或手动搜索城市。任何定位方式无法识别城市时，页面会清空地点和天气值并停止发送，不会使用“当前位置”作为占位城市。已经取得有效天气后，外部服务偶发失败会保留并继续发送上一次数据，同时在网页显示更新失败原因并等待下次重试；首次查询失败且没有有效数据时不会发送。

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

这个文件在 `app.web_port` 中保存默认网页端口，在 `app.dismissed_release_notes_version` 中保存已关闭提醒的版本号，同时保存 OSC 映射、DG-LAB 设置、ChatBox 文本、批量轮播开关和间隔、心率设备地址、帧率广播设置、正在播放广播设置、天气广播开关和间隔等本地配置。配置与程序文件分开保存，覆盖升级时会继续保留。它是本机配置文件，不会提交到 Git 仓库。

## 打包 EXE

项目不保留固定的 `build_exe.bat` 或 `build_exe.ps1` 打包脚本。

需要打包时按照 [packaging/README.md](packaging/README.md) 执行一次性 PyInstaller 和 Inno Setup 命令，最终只输出安装包：

```text
dist\vrctool-setup-2.5.0.exe
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
  now_playing.py        QQ 音乐/网易云媒体会话检测与 ChatBox 广播
  weather.py            自动定位、天气查询和 ChatBox 广播
  osc.py                VRChat OSC 监听和映射
  update_manager.py     GitHub Release 检查、下载和更新安装
  release_notes.py      当前版本更新内容和按版本提醒判断
  assets/               Logo 等资源
  web/                  网页前端
packaging/              PyInstaller 和 Inno Setup 打包配置
third_party/presentmon/ PresentMon 2.4.1 x64 与 MIT 许可证
tests/                  命令行、安装、配置迁移、帧率、天气和应用更新自动测试
references/legacy/      早期参考脚本
docs/images/            README 界面截图
requirements.txt        Python 依赖
run.bat / run.ps1       本地启动入口
```

## 开源项目致谢

感谢开源项目 [ccvrc/DG-LAB-VRCOSC](https://github.com/ccvrc/DG-LAB-VRCOSC) 为本项目的开发提供参考。

感谢 [Intel PresentMon](https://github.com/GameTechDev/PresentMon) 提供 Windows 显示呈现事件采集能力。本项目随安装包分发未修改的 PresentMon 2.4.1 x64 二进制，其 MIT 许可证保存在 `third_party/presentmon/LICENSE.txt`。
