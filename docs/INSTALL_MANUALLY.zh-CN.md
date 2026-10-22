# 手动安装（开发者可选）

普通用户优先使用项目根目录的 Setup-Ally 安装入口，见[使用手册](../USER_GUIDE.zh-CN.md#setup)。本页保留手动准备环境的方法；命令均在项目主文件夹执行。

## 手动准备依赖

#### 1. 安装 Python 和 Node.js

点击对应系统的安装包，下载后双击安装。Python 用于运行合同分析程序，Node.js 用于运行 Word 插件页面。

| 软件 | Windows 64 位（Intel / AMD） | Mac |
| --- | --- | --- |
| Python 3.12.10 | [下载安装包（.exe）](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe) | [下载安装包（.pkg）](https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg) |
| Node.js 24.22.0 LTS（包含 npm） | [下载安装包（.msi）](https://nodejs.org/dist/v24.22.0/node-v24.22.0-x64.msi) | [下载安装包（.pkg）](https://nodejs.org/dist/v24.22.0/node-v24.22.0.pkg) |

Windows 安装 Python 时，勾选 **Add python.exe to PATH**，再点击 **Install Now**。以上是本手册使用的版本示例。

#### 2. 安装 PromptFlow 和 OpenAI Python SDK

这两个组件用于组织合同分析流程和调用模型。保持联网，按自己的系统操作，每条命令执行结束后再继续下一步。

**Windows：**

1. 打开项目主文件夹，例如 `D:\ally-legal-assistant-main`。点击文件夹顶部地址栏，输入 `powershell`，按回车。
2. 复制下面一行，按回车，创建项目专用的 Python 环境：

   ```powershell
   py -3.12 -m venv .venv
   ```

   **完成后：** 项目内生成 `.venv` 文件夹，窗口重新可以输入命令。

3. 回到第 1 步打开的 **PowerShell 窗口**，例如输入位置显示 `PS D:\ally-legal-assistant-main>`。复制下面一行，按回车，下载并安装组件：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend/PromptFlow/legal-main-flow/requirements.txt
   ```

**Mac：**

1. 打开“终端”，输入 `cd `（末尾有一个空格），将项目主文件夹拖入终端，再按回车。
2. 复制下面一行，按回车，创建项目专用的 Python 环境：

   ```bash
   python3.12 -m venv .venv
   ```

   **完成后：** 项目内生成隐藏的 `.venv` 文件夹，终端重新可以输入命令。

3. 回到第 1 步打开、已经进入项目主文件夹的 **“终端”窗口**。复制下面一行，按回车，下载并安装组件：

   ```bash
   .venv/bin/python -m pip install -r backend/PromptFlow/legal-main-flow/requirements.txt
   ```

**安装完成后：** 窗口通常显示 `Successfully installed ...`，然后重新可以输入命令。PromptFlow 和 OpenAI SDK 保存在 `.venv` 中。

#### 3. 安装插件页面组件

继续使用上面“2. 安装 PromptFlow 和 OpenAI Python SDK”时打开的命令窗口：Windows 是 **PowerShell**，Mac 是 **终端**。在刚完成组件安装的位置，执行下面对应的命令。

**Windows：**

```powershell
npm.cmd install
```

**Mac：**

```bash
npm install
```

**完成后：** 项目内出现 `node_modules` 文件夹，窗口显示 `added ... packages` 或 `up to date`。

## 初始化本地分析流程

首次部署执行一次；已经能正常使用本项目的用户可跳过。回到上一步执行 `npm.cmd install`（Windows）或 `npm install`（Mac）的命令窗口，执行下面对应的命令，创建本地 `ally` 连接。

**Windows：**

```powershell
.\.venv\Scripts\pf.exe connection create --file backend/PromptFlow/legal-main-flow/connection.local.yaml
```

**Mac：**

```bash
.venv/bin/pf connection create --file backend/PromptFlow/legal-main-flow/connection.local.yaml
```

**完成后：** 窗口显示名称为 `ally`、类型为 `custom` 的连接信息。系统提示保存本地凭据时，按提示允许。真实模型密钥稍后在 Word 中填写。



