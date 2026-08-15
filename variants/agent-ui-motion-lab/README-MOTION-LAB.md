# 诗行万里 · 动画实验室

这是从当前 Agent UI 独立复制出的筛选版本。原前端不在本目录内，实验版使用独立
`3011` 端口，共用只读证据后端 `8123`。

## 三组动画

- **水墨行旅**：审核行迹按史料段逐笔显现，视觉转场保持缺口语义，并在抵达时落下地点章。
- **电影卷轴**：双层暖纸遮幅完成后才换幕，诗句、事件与情绪分层显影。
- **意象潮汐**：词项切换时重排对读图、滚动真实数值，并同步揭示对应证据。

右上角“动画实验室”可即时切换：

- `克制`：短时、低位移，适合稳定演示。
- `电影`：完整转场与镜头节奏，默认推荐。
- `实验`：更长余波与更强舞台效果，适合筛选创意。
- 总开关关闭或系统开启“减少动态效果”时，内容立即切换，不等待动画。

## 启动

需要 Node.js `20.9.0` 或更高版本（与 Next.js 16 的运行要求一致）。实验副本复用现有
依赖目录联接，无需再次安装依赖。开发命令已固定使用 Webpack，以兼容该目录联接；
生产构建同样显式使用 Webpack。

开发模式：

```powershell
.\variants\agent-ui-motion-lab\start-motion-lab.ps1
```

验收后的构建模式：

```powershell
.\variants\agent-ui-motion-lab\start-motion-lab.ps1 -Production
```

打开 `http://127.0.0.1:3011/`。现有 `http://127.0.0.1:3000/` 不会被占用或停止。

只停止实验版网页：

```powershell
.\variants\agent-ui-motion-lab\stop-motion-lab.ps1
```

停止脚本不会关闭共用的 `8123` 后端。

## 备份边界

- 动画实验副本：`variants/agent-ui-motion-lab`
- 当天原版基线：`variants/_baseline-agent-ui-20260809`
- 原版保护哈希：`variants/original-protection-hashes.json`

所有动画开发只发生在实验副本中。完成验收时会再次用保护哈希核对原前端。
实验副本的 `node_modules` 是指向原前端依赖目录的目录联接；联接存在时不要在实验
副本中执行 `npm install` 或 `npm ci`。它只共享依赖，不共享任何 `src`、配置或构建产物。

精确复位时不要在实验目录上做“覆盖复制”，因为那会留下基线中不存在的动画文件。
先停止实验版并保留整个 `agent-ui-motion-lab` 作为归档，再从当天基线复制出一个新的
并列目录（例如 `agent-ui-restored-20260809`），最后只为新目录重建指向原前端依赖的
`node_modules` 目录联接。这样得到的才是逐文件等同基线的恢复副本；Motion Lab 启停脚本
不会出现在恢复副本中，这是预期结果。绝不要反向覆盖基线，也不要删除或替换
`apps/agent-ui/web` 原前端。

## 开发验证

```powershell
npm --prefix variants\agent-ui-motion-lab run lint
npm --prefix variants\agent-ui-motion-lab run typecheck
npm --prefix variants\agent-ui-motion-lab run test
npm --prefix variants\agent-ui-motion-lab run build
```
