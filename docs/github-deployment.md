# GitHub 自动部署

`main` 分支每次 push 后，GitHub Actions 会在 GitHub Runner 上完成前端构建、
前后端测试和打包。服务器只接收成品、切换 release、重启 systemd 服务并做健康检查；
检查失败会恢复上一版。

## 仓库 Secrets

在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 配置：

- `DEPLOY_HOST`：服务器公网 IP。
- `DEPLOY_USER`：当前服务器填 `root`。脚本需要写 `/opt`、`/var/www`、
  `/etc/systemd/system` 并重启服务；若以后改用普通部署用户，必须只授予这些命令的
  受限 sudo 权限，并同步修改 workflow 的调用方式。
- `DEPLOY_SSH_KEY`：该用户的 SSH 私钥。
- `DEPLOY_KNOWN_HOSTS`：`ssh-keyscan -H <server-ip>` 的完整输出。

私钥、模型 API Key 和 `.env` 不得提交到仓库。模型未配置时 Agent API 的
`/health` 可以处于 `degraded`，但目录、知识库和直接数据接口仍须返回 HTTP 200。

## 服务器目录

- 前端 release：`/opt/shixing-agent-ui-standalone/releases/<git-sha>`
- 前端当前版本：`/opt/shixing-agent-ui-standalone/current`
- Agent release：`/opt/shixing-agent-api/releases/<git-sha>`
- Agent 当前版本：`/opt/shixing-agent-api/current`
- 持久知识库：`/opt/shixing-wanli-source/诗行万里/output/assets/knowledge`
- 参赛静态站 release：`/var/www/shixing-wanli-releases/<git-sha>`
- 参赛静态站当前版本：`/var/www/shixing-wanli`

Agent API 以 Python 3.12 PEX 自包含发布，不依赖服务器旧虚拟环境中的包版本。
部署不会提交或传输 `output/assets/knowledge/`、embeddings、虚拟环境、`.env`
或本地缓存。知识库、向量和 Agent 缓存继续由服务器上的持久目录提供。

首次自动部署前，服务器须已存在 `shixing-agent-web.service` 和
`shixing-agent-api.service` 主 unit，并安装 `/usr/local/bin/node` 与
Python 3.12；部署脚本会验证这些前提，并用版本化 drop-in 固定两个服务的启动路径。

## 日常更新

```bash
git add -A
git commit -m "describe the change"
git push origin main
```

可在仓库 `Actions` 页面查看构建、部署和公网检查结果。需要重新部署同一提交时，
使用 `Build and deploy` 工作流的 `Run workflow`。
