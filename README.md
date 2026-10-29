# 大麦抢票自动化系统

一个基于Selenium和Appium的大麦网抢票自动化工具，支持Web端和移动端抢票。

## 🚀 功能特性

- **双端支持**：支持Web端（Selenium）和移动端（Appium）抢票
- **预填购票**：移动端 V2 优先保留有效预填，必要时恢复配置票档和数量；到点购买、选票确定、订单核验后最终提交，付款由用户完成
- **提前准备**：复用 Appium 连接并缓存已核验的购买入口，支持按钮文字隐藏的已适配详情页
- **可配置**：灵活的配置文件，支持多种演出设置
- **防重复提交**：预填模式仅尝试提交一次，记录提交状态，结果不明时不重复下单

## 📋 系统要求

### 基础环境
- **Python**: 3.9+
- **操作系统**: macOS / Windows / Linux

### Web端抢票
- **Chrome浏览器**: 最新版本
- **ChromeDriver**: 自动下载

### 移动端抢票
- **Node.js**: `^20.19.0 || ^22.12.0 || >=24.0.0`，**npm**: 10+（Web端不需要）
- **Android SDK**: 已配置环境变量
- **Appium**: 3.x，另需安装 UiAutomator2 驱动
- **Java/JDK**: 按所装 UiAutomator2 驱动的 doctor 检查结果配置 `JAVA_HOME`
- **Android设备**: 真机或模拟器

## 🛠️ 安装指南

### 1. 克隆项目
```bash
git clone <repository-url>
cd ticket-purchase
```

### 2. 安装Python依赖
以下 Windows PowerShell 命令在项目根目录执行，使用 Python 3.9 或更新版本：

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# 两端都需要：安装 Web 和移动端 Python 依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 仅 Web 端可改用：
# .\.venv\Scripts\python.exe -m pip install -r damai\requirements.txt

# 仅移动端可改用：
# .\.venv\Scripts\python.exe -m pip install -r damai_appium\requirements.txt
```

直接使用虚拟环境里的 Python，无需激活脚本或修改 PowerShell 执行策略。macOS/Linux 可将 Python 路径改为 `.venv/bin/python`。

如使用 Poetry，两端执行 `poetry install --extras mobile`；仅 Web 端执行 `poetry install`。随后用 `poetry run python` 替代下面的虚拟环境 Python 命令。

### 3. 移动端环境配置（仅移动端抢票需要）

#### 3.1 安装Node.js
安装符合上述版本范围的 Node.js，重新打开 PowerShell 后验证：

```powershell
node --version
npm.cmd --version
```

#### 3.2 安装Appium
```powershell
# 固定 Appium 主版本；Windows 使用 .cmd 避免执行 npm.ps1
npm.cmd install -g appium@3

# 先确认服务端安装成功，再安装并检查驱动
appium.cmd --version

# 安装UiAutomator2驱动
appium.cmd driver install uiautomator2

# 检查 Android SDK、JDK 等驱动依赖，按输出修复必需项
appium.cmd driver doctor uiautomator2
```

#### 3.3 配置Android环境
通过 Android Studio 的 SDK Manager 安装 Android SDK、Platform-Tools，以及所需平台/模拟器组件。在 PowerShell 配置当前会话：

```powershell
# 示例为常见默认位置；请按 SDK Manager 显示的真实安装目录修改
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\emulator;$env:Path"

# 验证ADB
adb devices
```

`JAVA_HOME` 应指向满足所装 UiAutomator2 驱动要求的 JDK，按 `appium.cmd driver doctor uiautomator2` 输出核验。上述环境变量仅影响当前 PowerShell；新窗口中需重新设置或提前保存到系统环境变量。

## ⚙️ 配置说明

### 移动端配置 (damai_appium/config.jsonc)

文件扩展名虽为 `.jsonc`，当前解析器按标准 JSON 读取，请勿加入注释。当前指南使用 `prefilled_mode: true`：先在手机完成场次、票档、数量和观演人预填，再回到演出详情。脚本提前核验标题、预填“已完成”状态和购买栏坐标，到点点击购买；优先保留有效预填，不重新勾选观演人，也不自动搜索或切换城市。若票档未生效，会按配置恢复；数量正确不重复加票，数量不符则按差额逐张调整并等待回显。

下面是通用格式示例，不代表任何实际购票目标。请填写自己的实际演出、场次、票档和观演人；`sale_start_time` 是北京时间 UTC+8 的开售时间，不是演出时间，自动运行时必须仍在未来。示例时间过期后不能复用。

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

#### 配置参数说明

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `server_url` | string | Appium服务器地址 | `"http://127.0.0.1:4723"` |
| `keyword` | string | 用于核验演出详情及订单目标，不自动搜索 | `"示例演出"` |
| `users` | array | 观演人员名单 | `["张三", "李四"]` |
| `city` | string | 用于匹配演出标题中的城市，不切换城市 | `"示例城市"` |
| `date` | string | 实际演出场次；预填模式在订单确认页核对，包含完整年月日和需要核对的时间 | `"2026-12-31 19:30"` |
| `price` | string | 配置票档价格；预填未生效时用于恢复票档，订单确认页再次核对 | `"看台100元"` |
| `price_index` | number | 从 0 开始的票档索引；价格文字不可识别时用于恢复配置票档，需按实际页面核对 | `0` |
| `prefilled_mode` | boolean | true 使用预填购票流程；省略或 false 使用旧模式 | `true` |
| `if_commit_order` | boolean | true 在核验通过后自动提交锁单；此授权不包括付款 | `true` |
| `sale_start_time` | string | 预填模式必填且必须是未来实际开售时间，格式 YYYY-MM-DD HH:MM:SS，北京时间 UTC+8 | `"2026-12-01 10:00:00"` |
| `order_flow_timeout` | number | 首次购买点击后的页面处理等待时限，默认 60 秒，范围 1–180 秒；页面查询耗时会影响实际退出时刻 | `60` |
| `wait_poll_interval` | number | 旧模式待命查询间隔，默认 0.5 秒；预填模式使用独立的准备和等待节奏 | `0.5` |
| `device_name` | string | 可选，设备名称；省略时为 Android | `"Android"` |
| `platform_version` | string | 可选，设备 Android 版本；省略或空值时自动识别 | `"14"` |
| `udid` | string | 可选，adb devices 显示的序列号；多设备时指定 | `"emulator-5554"` |

`users` 必须与手机预填的观演人一致且不能重复，预期张数为名单人数。选票页实际数量必须可读且匹配，才能点“确定”进入订单确认页；不能仅凭原生 `enabled=true` 判定按钮可用。订单确认页只读核对演出、场次、票档、数量和观演人，通过后才最终提交一次；如展示总额，也会核对。验证码需本人在平台界面完成，脚本不代做验证。

目前已做页面解析模拟与实机详情的只读验证，尚未通过真实下单验收。详情准备通过不代表后续原生确认页一定能识别；不保证到点后手机执行或服务端锁单的时延，也不保证购票成功。

### Web端配置 (damai/config.json)

首次使用且尚无配置文件时，在项目根目录执行 `Copy-Item .\damai\config.example.json .\damai\config.json`，再填写真实演出和观演人信息。

```json
{
  "index_url": "https://www.damai.cn/",
  "login_url": "https://passport.damai.cn/login",
  "target_url": "https://detail.damai.cn/item.htm?id=xxx",
  "users": ["张三", "李四"],
  "city": "广州",
  "dates": ["2026-11-01"],
  "prices": ["1039"],
  "if_listen": true,
  "if_commit_order": false,
  "max_retries": 1000
}
```

## 🚀 使用方法

### 移动端页面检查与运行

#### 1. 启动Android设备
```powershell
# 在已配置 Android 环境变量的 PowerShell 中列出模拟器，再按实际名称启动
emulator -list-avds
emulator -avd YourAVDName

# 或连接真机（需开启USB调试）
adb devices
```

#### 2. 安装大麦APP
在 Android 设备上安装大麦 APP 并登录，进入正确演出，完成场次、票档、数量和观演人预填，确认显示“已完成”，再回到演出详情。不要停在预约选票页。

#### 3. 启动Appium服务器
```powershell
# 在已配置 Android/JDK 环境变量的 PowerShell 窗口中运行，保持此窗口打开
appium.cmd --port 4723
```

#### 4. 配置抢票参数
编辑 `damai_appium/config.jsonc` 文件，设置：
- `prefilled_mode: true`、`if_commit_order: true`（自动提交锁单，付款由用户完成）
- 演出关键词 `keyword`、城市 `city`、实际场次 `date`、票档 `price` 和观演人 `users`，与手机预填保持一致
- 必填未来实际开售时间 `sale_start_time`（北京时间 UTC+8）和页面处理时限 `order_flow_timeout`（默认 60 秒）
- 需要时填写 `udid`、`platform_version` 等设备参数
- 其他参数

#### 5. 先检查当前页面

保持手机解锁、目标页面在前台，另开 PowerShell，从项目根目录运行只读诊断：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2 --check-page
```

此命令只连接并读取当前页面，不点击、不执行购票，也不等待开售时间。在预填模式中，它判断详情标题、预填“已完成”状态及入口坐标是否准备好，通过时输出购买栏坐标范围；已适配的入口即使文字隐藏、`clickable=false`，也可根据已核验的控件边界准备。摘要保存在项目目录的 `logs/mobile-page-check.json`，不保存原始 XML、截图或观演人数据。此检查不等于真实下单验收。

#### 6. 提前运行预填流程
确认开售时间仍在未来，保持手机解锁、正确演出详情页在前台，不再切页面、滚动或改变屏幕方向。可在开售前 3–5 分钟另开 PowerShell，从项目根目录执行，提前建立 Appium 连接：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m damai_appium.damai_app_v2
```

脚本首次读取整页 XML 核验详情并缓存入口坐标，之后待命仅轻量检查大麦前台、锁屏状态、屏幕方向和尺寸，T−2 秒也不再读取整页 XML。随后用本机单调时钟（monotonic）等待，T0 发送缓存坐标点击，不等待按钮文字变化、不重新建立会话。终端显示的本机点击发送偏差不包含手机执行、网络与服务端处理耗时。过期的开售时间会直接拒绝点击。按 `Ctrl+C` 可退出。

流程必须经过“选票页确定 → 原生订单确认核验 → 最终提交 → 待支付／立即付款页”。页面分类优先识别 SKU 结构，选票页中的“确定”不算最终提交。未选票档时，即使原生控件报告 `enabled=true`，也会等待实际数量可读且正确再确认。

预填票档未生效时，先按 `config.price` 匹配，必要时用已配置且核对过的 `price_index` 恢复；配置票档缺货或索引对应可读价格不符时停止，不改买更贵或其他价格。实际数量等于名单人数时不重复加票；不符时按差额逐个加减，每次等待数量回显后再继续，不重新勾选姓名。原生订单确认页核验通过后精确提交一次；取得订单号及待支付证据才报告已锁单。到待支付／立即付款页停止自动点击，由用户核对并付款，脚本不实际支付。

未知页面会在 `order_flow_timeout` 内继续只读识别，不采用旧模式的开售后 3 秒接管规则。遇到真正的平台验证码，请本人在手机完成，程序可继续观察后续页面。只有订单确认核验通过才记录最终提交，记录包含阶段、按钮及核验结果。提交后若返回选票页，按结果不明处理，停止再次确认或提交以防重单；`logs/prefilled/` 保存跨重启防重复记录，不要随意删除，先在 APP 中核对是否已有待支付订单。同一设备的重复购票进程由操作系统锁阻止。

#### 旧模式兼容

`prefilled_mode: false` 或省略该字段会走旧流程：按 `price_index` 选票、按名单人数加票并点击观演人，不适用于保持已预填内容。旧模式仍需识别明确购买文字；配置开售时间时，开售后 3 秒起的下一次页面查询仍未识别会停止，未配置时间则保持等待。新指南中的隐藏入口点击、保留预填和防重复记录属于预填模式。

### Web端抢票

#### 1. 配置参数
编辑 `damai/config.json` 文件，设置目标演出URL和其他参数。

#### 2. 运行抢票脚本
从项目根目录执行：

```powershell
Set-Location damai
..\.venv\Scripts\python.exe damai.py
```

## 🔧 故障排除

### 常见问题

#### 1. Node.js版本不兼容
```
Error: Node version must be at least ^20.19.0 || ^22.12.0 || >=24.0.0
```
**解决方案**：安装符合 `^20.19.0 || ^22.12.0 || >=24.0.0` 的 Node.js，确保 npm 10+。重新打开 PowerShell，分别运行 `node --version` 和 `npm.cmd --version`；仅 Web 端无需安装 Node.js。

#### 2. Android环境变量未设置
```
Error: Neither ANDROID_HOME nor ANDROID_SDK_ROOT environment variable was exported
```
**解决方案**：设置环境变量
```powershell
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk" # 按真实安装位置修改
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\emulator;$env:Path"
```

#### 3. 设备连接问题
```
Error: Unable to find an active device or emulator
```
**解决方案**：
- 检查设备连接：`adb devices`
- 确保设备已开启USB调试
- 检查Android版本是否匹配

#### 4. Appium连接失败
```
Error: Connection refused
```
**解决方案**：
- 确保Appium服务器正在运行
- 检查端口4723是否被占用
- 验证服务器地址配置

#### 5. npm 安装 Appium 下载失败

`ECONNRESET` 表示下载连接中断；`EPERM` / `ENOTEMPTY` 多为 npm 清理临时目录的警告。应先处理下载失败，不能仅凭清理警告判断已安装成功。安装未完成时，`appium` 命令自然可能找不到。

```powershell
# 确认网络或代理可正常访问 npm 后重试
npm.cmd install -g appium@3 --fetch-retries=5
appium.cmd --version
```

若安装成功后仍找不到命令，运行 `npm.cmd prefix -g`，确认输出目录已加入用户 PATH 并重新打开 PowerShell。无需删除整个 npm 全局目录或关闭 SSL 验证。

#### 6. 卡在“标题核验”或“未识别入口”

先检查 `prefilled_mode` 是否为 true，手机是否处于已完成预填的正确演出详情，再运行 `--check-page`。预填模式不依赖隐藏购买栏的文字或 clickable 属性，但必须核验标题、预填状态及入口边界；准备失败不会盲点。点击后的未知页面会继续只读观察至 `order_flow_timeout`，这不代表已经锁单。原生确认页尚未真实下单验收，诊断通过也不保证后续流程成功。

#### 7. 开售时间过期或已有提交记录

预填模式拒绝使用过期时间，需填写下一次真实且未来的开售时间。发现提交记录时，先在大麦 APP 核对待支付订单和提交结果；不要删除 `logs/prefilled/` 或改时间来绕过防重复保护。

### 调试技巧

#### 1. 检查设备状态
```bash
# 检查连接的设备
adb devices

# 检查设备Android版本
adb shell getprop ro.build.version.release

# 检查设备是否完全启动
adb shell getprop sys.boot_completed
```

#### 2. 验证Appium连接
```bash
# 检查Appium服务器状态
curl http://127.0.0.1:4723/status
```

#### 3. 查看应用包名
```powershell
# 查看已安装的应用
adb shell pm list packages | Select-String damai
```

## 📁 项目结构

```
ticket-purchase/
├── damai/                    # Web端抢票
│   ├── damai.py             # 主程序
│   ├── config.py            # 配置类
│   ├── config.json          # 配置文件
│   ├── config.example.json  # Web 配置模板
│   └── requirements.txt      # 依赖文件
├── damai_appium/             # 移动端抢票
│   ├── damai_app_v2.py      # 优化版主程序
│   ├── damai_app.py         # 原版主程序
│   ├── config.py            # 配置类
│   ├── config.jsonc         # 配置文件
│   ├── requirements.txt     # 移动端 Python 依赖（包含 Web 端依赖）
│   └── app.md               # 应用说明
├── requirements.txt         # 两端 Python 依赖入口
├── tests/                    # 测试文件
├── doc/                      # 文档
├── img/                      # 图片资源
└── README.md                 # 说明文档
```

## 🎯 使用流程

### 移动端抢票完整流程

1. **环境准备**
   - 安装符合版本要求的 Node.js 和 npm
   - 安装Appium和驱动
   - 配置Android SDK环境变量

2. **设备准备**
   - 启动Android模拟器或连接真机
   - 安装大麦APP并登录

3. **配置参数**
   - 编辑 `config.jsonc` 文件
   - 设置演出信息、观演人员等

4. **启动服务**
   - 启动Appium服务器
   - 验证设备连接

5. **执行抢票**
   - 在模拟器上打开大麦APP
   - 人工完成目标演出的场次、票档、数量和观演人预填，保持设备解锁、演出详情在前台
   - 设置 `prefilled_mode: true`、`if_commit_order: true` 及未来实际开售时间，先运行 `--check-page` 核验准备状态
   - 开售前 3–5 分钟从项目根目录运行 V2，提前连接，准备后到点点击

6. **监控结果**
   - 验证码本人完成，未知页面由程序在配置时限内继续只读识别
   - 看到订单号及待支付证据后核对订单并手动付款；提交结果不明时先查订单，不重复启动下单
   - 查看控制台输出
   - 检查订单状态

## ⚠️ 注意事项

1. **合法使用**：请遵守大麦网的使用条款，合理使用自动化工具
2. **账号安全**：建议使用专门的测试账号
3. **网络环境**：确保网络连接稳定
4. **设备性能**：建议使用性能较好的设备进行抢票
5. **时间设置**：提前设置好抢票时间，确保脚本在开售时间运行

## 🤝 贡献指南

欢迎提交Issue和Pull Request来改进项目。

## 📄 许可证

本项目仅供学习和研究使用，请勿用于商业用途。

---

**最后更新**: 2026年10月
**版本**: 2.0.0
