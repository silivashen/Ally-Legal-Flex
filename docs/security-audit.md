# 安全审查记录 — Ally Legal Flex 1.0.0

审查日期：2026-10-22 · 审查对象：本仓库源码与发布包 · 审查者：项目维护者（AI 辅助）

本文件记录一次**发布前自审**的范围、结论和仍未关闭的项。它不是第三方认证，也不代表今后版本的
安全性；每个版本都应重新核对「未覆盖项」与「发布前检查清单」。

---

## 1. 结论摘要

| 结论 | 数量 | 说明 |
| --- | --- | --- |
| 已修复（会影响使用或安全边界） | 3 | 启动器误判、`.cmd` 编码、缺单实例锁 |
| 已缓解（有替代控制） | 2 | 依赖版本锁定、诊断信息清除 |
| 接受并记录（已知限制） | 3 | API Key 明文、运行期 dev-server、无 CSP |
| 仅记录（当前不可利用） | 2 | `innerHTML` 拼接、SSO 死代码 |

**没有发现**：远程代码执行、路径穿越、任意文件读写、密钥经接口回显、反序列化、命令注入。
**主要风险**集中在**分发形态**（本地服务 + 明文凭据）与**运行期依赖**，而非业务逻辑。

---

## 2. 范围与方法

覆盖：

- `index_server.py`、`model_config_server.py`、`local_api_security.py`（四个本地服务的两个）
- `scripts/start_ally.py`、`scripts/setup_ally.py`、`Start-Ally.cmd/.command`、`Setup-Ally.*`
- `src/` 前端（task pane、Config、shared）
- `policy_excel.py`（Excel 导入/导出）、`contract_index.py`（合同索引）
- `webpack.config.js`、`manifest.xml`、`package.json`、`requirements.txt`
- 发布包内容、`.gitignore` / `.gitattributes`、文档与许可声明

方法：

1. 逐文件阅读上述代码，核对输入校验、鉴权、错误处理与文件写入路径。
2. 全仓密钥扫描：152 个文本文件，60 条原始命中，逐条人工判定后**全部为误报**
   （语义化版本号、示例邮箱 `jhon.doe@microsoft.com`、测试用合成字符串）。**未发现真实凭据。**
3. `npm audit`（含 `--omit=dev` 对比）。
4. 与本机安装环境比对依赖版本与许可证元数据。
5. 用真实日志与真实启动过程验证修复效果（见第 4 节证据）。

未做：渗透测试、模糊测试、macOS 真机验证、Docker 镜像审查、第三方源码审计。

---

## 3. 威胁模型

| 主体 | 能力 | 本项目的应对 |
| --- | --- | --- |
| 恶意网页（浏览器） | 向 `127.0.0.1` 发起请求 | 校验 `Origin` 白名单、`Host` 必须为回环地址、POST 强制 `application/json` |
| 同机其他进程 | 可伪造任意请求头 | **不在防护范围内**：同用户进程默认被信任 |
| 拿到项目文件夹的人 | 读取任意文件 | 仅靠 `.gitignore` 与打包白名单；**API Key 仍为明文**（见 F6） |
| 模型服务商 | 接收合同文本 | 无法控制；已在文档中披露“本地≠离线” |

---

## 4. 发现明细

### F1 启动器把可恢复的警告当成致命错误（已修复，中）

- **现象**：Word 已成功载入插件，启动器却报「Word 插件启动未获成功确认」，随后终止全部四个服务。
- **根因**：`office_started()` 用 `not re.search("Unable to |Failed to |\bError:")` 一刀切；
  `office-addin-debugging` 在没有管理员权限时打印
  `Failed to add loopback exemption.`，随后仍正常 sideload。
- **证据**：`.ally-run/<ts>/word.log` 中 `Sideloading...` → `Started.` 与拒绝访问提示同时存在。
- **影响**：可用性（用户无法使用），不涉及数据泄露。
- **修复**：[scripts/start_ally.py](../scripts/start_ally.py) 将该警告从致命标记中排除，改为
  “载入成功 + 可操作提示”，并打印可复制的 `CheckNetIsolation.exe` 修复命令。
- **回归**：`tests/test_start_ally.py::test_loopback_warning_is_not_a_startup_failure`。

### F2 `.cmd` 编码与行尾导致解析错位（已修复，中）

- **现象**：双击启动出现 `'Legal' 不是内部或外部命令`、`'hon.exe" (' …` 等碎片报错。
- **根因**：`.cmd` 使用 LF 行尾 + UTF-8 中文 + `chcp 65001`；cmd.exe 按字节偏移读取批处理，
  多字节字符使偏移漂移，从行中间重新解析，把字符串碎片当命令执行。
- **影响**：启动失败，且报错与真实原因无关，用户无法自救。
- **修复**：两个 `.cmd` 改为**纯 ASCII + CRLF**（中文提示由 Python 输出）；新增
  [.gitattributes](../.gitattributes) 强制 `*.cmd`=CRLF、`*.command`/`*.sh`=LF，防止再次被改坏。

### F3 缺少单实例保护（已修复，低）

- **现象**：双击两次会启动两套服务；Windows 下两个 `flow` 进程可同时绑定 8083，请求分流不确定。
- **修复**：项目级文件锁 `.ally-run/launcher.lock`；第二个窗口直接提示“已有启动器在运行”，
  不再争用端口。已运行的本项目服务在启动时**被识别并复用**（按命令行匹配项目路径）。

### F4 运行期依赖包含已知漏洞（接受，中）

- **事实**：`npm audit` 报告 109 条（10 critical / 61 high / 30 moderate / 8 low），
  但 `--omit=dev` 为 **0 条**。
- **问题**：分类上属于 `devDependencies`，实际却运行在用户机器上——
  插件页面由 `webpack-dev-server@5.0.3` 提供，证书由 `office-addin-dev-certs@1.13.3` 生成
  （依赖 `node-forge@1.3.1`，含多条 high 级 ASN.1 缺陷）。
- **缓解**：服务仅绑定 `127.0.0.1`、`allowedHosts` 限制为本机、插件页面走 HTTPS、
  项目不对外监听。
- **计划**：下一版本改为「构建产物 `dist/` + 极简静态 HTTPS 服务」，把整条 dev 工具链移出运行时。

### F5 Python 依赖未锁定（已修复，低 / 供应链）

- **原状**：`requirements.txt` 仅 `promptflow` / `openai` 两行，无版本约束，安装不可复现。
- **修复**：固定为本次验证版本 `promptflow==1.18.5`、`openai==3.36.0`。
- **残留**：传递依赖仍由安装器解析（不生成跨平台 lock 文件，避免 Windows 专属包破坏 macOS 安装）。

### F6 API Key 明文存储（接受，低–中，CWE-312 / CWE-522）

- **事实**：`model_config.json` 以明文保存 `api_key` 与 `embedding_key`，位于**项目根目录**。
- **已具备的控制**：文件在 `.gitignore` 与打包白名单中排除；接口只返回 `has_api_key` 布尔值，
  密钥从不回显给前端；更换 `base_url` 时强制重新输入 Key，避免把旧 Key 发往新地址。
- **风险边界**：可防“误提交 / 误打包”，**不能防**“整个文件夹被压缩发送或被其他本机账户读取”。
- **本期决定**：先做文档披露（README、用户手册、START_HERE），加密存储留待后续版本
  （Windows DPAPI + macOS Keychain）。
- **复现**：`Get-Content model_config.json`（本机）。

### F7 诊断产物含个人信息（已修复，低）

- **事实**：`.ally-run/diagnostic-report.txt`（136 KB）包含 `C:\Users\<用户名>`、
  端口占用进程的完整命令行（含与本项目无关的程序）。
- **风险**：被当作“诊断信息”贴到 issue 时泄露本机环境。
- **修复**：已删除该文件与历史运行日志；`scripts/package_release.py` 对运行期目录与日志做强制排除。

### F8 错误信息通过 `innerHTML` 写入（记录，信息）

- **位置**：[src/taskpane/taskpane.js:171](../src/taskpane/taskpane.js#L171)。
- **现状**：拼接的 `message` 来自固定字符串或 `Error` 对象，**当前不可利用**。
- **建议**：改为 `textContent` / `replaceChildren`，作为纵深防御；不阻塞本次发布。

### F9 缺少 CSP、依赖两个 Microsoft CDN（记录，信息）

- `taskpane.html` 从 `appsforoffice.microsoft.com` 加载 Office.js，从 `static2.sharepointonline.com`
  加载 Fabric CSS，且未设置 `Content-Security-Policy`。
- **建议**：后续加入 `script-src`/`style-src` 白名单，限制第三方脚本的影响面。

### F10 SSO 路径为死代码且有缺陷（记录，信息）

- `sso()` 调用 Graph 时使用 `Authorization: <token>`，缺少 `Bearer ` 前缀，无法工作；
  且 `src/config/config.json` 中 `sso-enabled: false`，该分支不执行。
- **建议**：删除 MSAL 相关代码与 `@azure/msal-browser` 依赖（约 805 KiB），减少攻击面。

---

## 5. 已核对有效的防护

这些是逐项读过代码确认的，不是假设：

- 本地服务校验 `Host`（仅回环 + 指定端口）与 `Origin` 白名单；POST 强制 JSON、限制体积。
- 模型配置接口**从不返回密钥**；连接测试禁止跟随重定向，避免把 `Authorization` 带到新目标。
- 合同索引文件名由内容/SHA-256 生成，`doc_id` 不参与路径拼接（无路径穿越）。
- Excel 导入：限制 3 MB / 500 条 / 解压后 16 MB，拒绝重复条目、加密包、公式、DTD/实体、外部链接；
  导出使用 `inlineStr`，不产生可执行公式。
- 写入均为「临时文件 + `os.replace`」原子替换；策略变更会失效向量缓存。
- Setup 下载 uv/Node：强制 HTTPS、SHA-256 固定、拒绝 zip-slip 与符号链接、使用 `tarfile.data_filter`。
- 全仓未使用 `shell=True`、`eval`、`pickle`、`yaml.load`（仅 `ast.literal_eval`）。

---

## 6. 依赖与许可

- 前端运行时依赖 3 个（MIT），`npm audit --omit=dev` 为 0 条。
- Python：直接依赖已锁定；传递依赖未做完整 SBOM。
- 许可：**无 GPL/AGPL**。MPL-2.0 仅 **certifi** 一项，已在
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 中列出。
  （早期一次粗糙扫描误报 pandas/tiktoken/isodate 为 MPL，实为匹配到了许可证正文中的
  `IMPLIED` 一词，已更正。）

---

## 7. 未覆盖项

- macOS 真机路径（钥匙串、`security` 命令、`.command` 执行权限）未验证。
- Docker 部署路径（`backend/Docker/`）未审查。
- 未做 HTTP 重定向之外的网络层测试（代理、DNS 重绑定）。
- 未对上游 Microsoft 模板代码做逐行审计，仅确认许可与头部声明保留。

---

## 8. 发布前检查清单

```text
[ ] 运行 scripts/package_release.py，确认输出中 runtime/private 计数为 0
[ ] 确认包内无 model_config.json、prompt_settings.json、*.log、.ally-run/
[ ] 更新 THIRD_PARTY_NOTICES.md 中与本次安装版本不一致的条目
[ ] 运行全量测试：python -m unittest discover -s tests
[ ] 确认 LICENSE / SECURITY.md / docs/security-audit.md 已包含在发布包内
```

---

## 9. 复现本次结论

```powershell
# 全量测试（227 个）
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 运行时依赖漏洞（应为 0）
npm audit --omit=dev

# 启动器健康检查（不启动服务）
cmd /c "Start-Ally.cmd --check"
```
