# Docker 后台服务

此目录只打包 PromptFlow 后台服务。Word 插件界面和本地 Config 服务仍按项目原有方式启动。

## 模型 Key 的处理

聊天模型和向量模型使用前端 Config 保存的项目根目录 `model_config.json`。该文件留在本机，不进入 Git 或 Docker 镜像；`connections/ally.yaml` 只是框架所需的无 Key 占位连接。

`.dockerignore` 仅允许必要的程序文件进入构建上下文，Dockerfile 也只复制指定文件。不要将 Key 写进 Python 源码、Dockerfile 或 `connections/ally.yaml`。

## 构建与运行

以下命令供以后需要 Docker 部署时使用，均从项目根目录执行。先在前端保存模型和政策配置，确认 `model_config.json`、`policy.json` 已存在。

```sh
docker build -t ally-legal-flow backend/Docker/legal-main-flow-container

docker run --rm --name ally-legal-flow \
  -p 127.0.0.1:8083:8080 \
  --mount "type=bind,source=$(pwd)/model_config.json,target=/flow/model_config.json,readonly" \
  --mount "type=bind,source=$(pwd)/policy.json,target=/flow/policy.json,readonly" \
  ally-legal-flow
```

运行时通过只读挂载提供本机配置，模型 Key 不写入镜像层。启动前先停止占用 8083 端口的本地后台服务。前端保存配置时会替换文件；修改配置后应删除并重新创建容器，使文件挂载指向最新版本。

容器内产生的索引和向量缓存会随容器删除而丢失；上述命令没有配置它们的持久化存储。
