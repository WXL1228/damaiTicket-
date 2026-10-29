# 🚀 大麦抢票快速开始指南

## 📋 Windows PowerShell 安装（两端）

以下命令从项目根目录执行，需要 Python 3.9+。使用虚拟环境 Python 的完整路径，无需激活脚本或修改 PowerShell 执行策略。

```powershell
Set-Location C:\aiProject\ticket-purchase
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

仅 Web 端可安装 `damai\requirements.txt`；仅移动端可安装 `damai_appium\requirements.txt`。如使用 Poetry，两端执行 `poetry install --extras mobile`，并用 `poetry run python` 替代下方虚拟环境 Python 命令。

## 💻 Web 端启动

安装 Chrome。首次使用且尚无配置文件时，从项目根目录运行 `Copy-Item .\damai\config.example.json .\damai\config.json`。编辑 `damai/config.json`，填写目标演出 URL、观演人、`dates` / `prices` 数组、`if_listen` 和 `if_commit_order`。首次验证建议 `if_commit_order` 为 `false`。完整示例见 [README.md](README.md)。

```powershell
# 从项目根目录执行
Set-Location damai
..\.venv\Scripts\python.exe damai.py
```

Web 端无需安装 Node.js、Appium 或 Android SDK。

## 📱 移动端环境准备

### 第1步：安装 Appium 和驱动

移动端另外需要 Node.js `^20.19.0 || ^22.12.0 || >=24.0.0`、npm 10+，以及 Android SDK 和驱动要求的 JDK。安装 Node.js 后重新打开 PowerShell：

```powershell
node --version
npm.cmd --version
npm.cmd install -g appium@3

# 先确认安装成功，再安装驱动
appium.cmd --version
appium.cmd driver install uiautomator2
```

### 第2步：配置 SDK 和设备

通过 Android Studio 的 SDK Manager 安装 Android SDK、Platform-Tools 及所需平台/模拟器组件。路径按 SDK Manager 显示的真实安装位置填写：

```powershell
# 这是 Windows 常见默认位置，请按实际安装位置修改
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\emulator;$env:Path"

adb devices
appium.cmd driver doctor uiautomator2
```

按 doctor 输出修复必需项，并将 `JAVA_HOME` 指向符合所装 UiAutomator2 要求的 JDK。启动 Android Studio 中的模拟器，或连接已开启 USB 调试的真机并允许电脑调试；`adb devices` 应显示设备状态为 `device`。以上环境变量仅对当前 PowerShell 有效，新窗口需重新设置或保存到系统环境变量。

### 第3步：启动服务并检查页面

在已配置好 Android/JDK 环境的 PowerShell 中启动服务，保持窗口打开：

```powershell
appium.cmd --port 4723
```

在 Android 设备上打开大麦 APP 并登录，人工进入目标演出，完成场次、票档、数量和观演人预填，确认显示“已完成”，再回到演出详情。保持手机解锁、详情在前台，不停在预约选票页。新预填模式优先保留有效预填，不搜索、切城市或重新勾选观演人；必要时按配置恢复票档，并根据实际数量按差额调整。

编辑下方配置后，先从项目根目录运行只读页面诊断：

```powershell
Set-Location C:\aiProject\ticket-purchase
.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2 --check-page
```

此命令只读检查，不点击、不执行购票、不等待开售时间。设置 `prefilled_mode: true` 后，它核验详情标题、预填“已完成”状态及入口边界，通过时输出坐标范围；已适配的隐藏文字入口也支持。摘要保存到项目目录的 `logs/mobile-page-check.json`，不保存原始 XML、截图或观演人数据。

目前仅完成页面解析模拟和实机详情只读验证，原生订单确认流程尚未通过真实下单验收。准备通过不保证后续页面可用或购票成功。

### 第4步：提前运行预填购票流程

按下方示例设置 `prefilled_mode: true`、`if_commit_order: true` 和未来实际开售时间。在开售前 3–5 分钟从项目根目录运行，保持详情页不切换、不滚动、不旋转屏幕：

```powershell
Set-Location C:\aiProject\ticket-purchase
.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2
```

程序首次读取整页 XML 核验详情并缓存入口坐标，之后待命仅轻量检查前台、锁屏、屏幕方向和尺寸；T−2 秒也不再读取整页 XML。最后窗口按本机单调时钟（monotonic）等待，T0 发送坐标点击，不等按钮文字变化、不重新建会话。终端的本机点击发送偏差不包含手机执行、网络或服务端锁单耗时，不能保证毫秒抢到。过期开售时间会直接拒绝点击，`Ctrl+C` 可退出。

流程为“选票页确定 → 原生订单确认核验 → 最终提交 → 待支付／立即付款页”，不实际支付。SKU 结构识别优先于提交文案，选票“确定”不算最终提交；未选档时原生 `enabled=true` 也不能证明可确认，必须读到正确实际数量。

预填票档未生效时，按 `config.price` 或已核对的 `price_index` 恢复，配置票档缺货不改买更贵或其他价格。数量已等于名单人数就不重复加票；不符则按差额逐个加减，每次等待回显。订单确认页核对演出、场次、票档、数量、观演人后最终提交一次。取得订单号及待支付证据才报告锁单；到待支付／立即付款页停止自动点击，由本人付款。

未知页面会继续只读分类，等待至 `order_flow_timeout`，不采用旧模式的开售后 3 秒接管规则。真正的平台验证码需本人在手机完成，之后程序可继续观察。最终提交记录包含阶段、按钮及核验结果；提交后回到选票页属于结果不明，不再确认或提交。先查手机待支付订单，不要随意删除 `logs/prefilled/` 的跨重启防重复记录。同一设备的重复购票进程由操作系统锁阻止。

macOS/Linux 可参考 [README.md](README.md) 并将 Python 路径改为 `.venv/bin/python`；项目中的 `.sh` 脚本需要 Bash，不能直接作为 PowerShell 命令执行。

## ⚙️ 配置抢票参数

编辑 `damai_appium/config.jsonc` 文件：

```json
{
  "server_url": "http://127.0.0.1:4723",
  "keyword": "示例演出",
  "users": ["观演人姓名"],
  "city": "示例城市",
  "date": "2026-12-31 19:30",
  "price": "看台100元",
  "price_index": 0,
  "prefilled_mode": true,
  "if_commit_order": true,
  "sale_start_time": "2026-12-01 10:00:00",
  "order_flow_timeout": 60,
  "wait_poll_interval": 0.5
}
```

请保持标准 JSON，不添加注释。以上为通用格式示例，不代表实际购票目标，需替换演出、城市、场次、票档和名单。观演人必须与手机预填一致且不得重复，预期数量为名单人数。`date` / `price` 在订单确认页核对；`price` 或从 0 开始的 `price_index` 也用于预填未生效时恢复票档，索引需按实际页面核对。

`sale_start_time` 必填，格式为 `YYYY-MM-DD HH:MM:SS`，表示北京时间 UTC+8 的未来实际开售时间，不是演出时间；示例时间一旦过期就不能复用。`order_flow_timeout` 默认 60 秒，可设 1–180 秒，表示首次购买点击后的页面处理等待时限，页面读取耗时会影响实际退出时刻。`wait_poll_interval` 留给旧模式，预填模式使用独立等待节奏。

需要时可增加 `"device_name": "Android"`、`"platform_version": "14"`、`"udid": "emulator-5554"`，按真实设备填写；多设备时指定 `udid`。`prefilled_mode: false` 或省略该字段可兼容旧流程，但旧流程会重选票档、增票、点击观演人，不适用于保持预填。

## 🔧 常见问题解决

### 问题1：Node.js版本不兼容
安装符合 `^20.19.0 || ^22.12.0 || >=24.0.0` 的 Node.js，确保 npm 10+，再打开新的 PowerShell 验证版本。仅 Web 端无需 Node.js。

### 问题2：Android设备未连接
```powershell
# 在已配置 Android 环境变量的窗口中，按实际名称启动模拟器
emulator -list-avds
emulator -avd YourAVDName

# 检查设备
adb devices
```

### 问题3：Appium服务器未启动
```powershell
# 在已配置 Android/JDK 环境变量的窗口中启动
appium.cmd --port 4723
```

### 问题4：npm 安装失败，找不到 appium

`ECONNRESET` 是下载连接中断，`EPERM` / `ENOTEMPTY` 多为清理警告；安装未完成时无法使用 `appium`。确认网络或代理后重试：

```powershell
npm.cmd install -g appium@3 --fetch-retries=5
appium.cmd --version
```

安装成功后仍找不到命令，可用 `npm.cmd prefix -g` 查看全局命令目录，确认其在用户 PATH 中并重新打开 PowerShell。无需删除整个 npm 全局目录或关闭 SSL 验证。

### 问题5：卡在“标题核验”或“未识别入口”

确认 `prefilled_mode: true`，手机停在显示预填“已完成”的正确详情页，再运行 `--check-page`。隐藏文字不妨碍已适配入口准备，但标题、预填和边界核验必须通过。点击后未知页面在配置时限内只读等待；原生确认页尚未真实下单验收，不能把等待当成已锁单。

### 问题6：提示开售时间已过或存在提交记录

过期时间不会触发点击，必须填写下一次真实且未来的开售时间。存在提交记录时，先在手机核对是否已有待支付订单，不要删除 `logs/prefilled/` 或改时间来绕过防重复保护。

## 📱 移动端抢票完整流程

1. **环境检查**：检查 Python、Node/npm、`adb devices` 和 `appium.cmd driver doctor uiautomator2`
2. **启动服务**：`appium.cmd --port 4723`
3. **手机预填**：完成场次、票档、数量及观演人预填，解锁手机并保持正确演出详情在前台
4. **配置参数**：启用 `prefilled_mode` 和 `if_commit_order`，填写一致的演出信息、名单、未来实际开售时间及等待时限
5. **页面诊断**：从项目根目录运行 `.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2 --check-page`，核验准备状态与坐标，不购票
6. **提前运行**：开售前 3–5 分钟运行 `.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2`；遇到验证码本人处理，程序继续观察
7. **核对并支付**：取得订单号和待支付证据后手动付款，结果不明先查订单，不重复提交

## ⚠️ 重要提醒

- 确保在开售时间前准备好所有环境
- 提前测试脚本运行是否正常
- 建议使用专门的测试账号
- 遵守大麦网使用条款

## 🆘 获取帮助

如果遇到问题，请：
1. 按本文依次检查 Python 依赖、设备连接和 Appium 驱动环境
2. 查看 `README.md` 详细文档
3. 检查控制台错误信息
4. 确认所有依赖已正确安装

---

**祝您抢票成功！** 🎫✨
