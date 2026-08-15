# CBDB 身份审计

`tools/cbdb_identity_audit.py` 是独立、离线且只读的 88 位诗人 CBDB 身份审计器。

## 输入与匹配规则

- 默认只读 `.cache/background_sources/cbdb/latest.sqlite3`，连接使用 SQLite `mode=ro` 与 `PRAGMA query_only`；全部 `SELECT` 包含在一个显式只读事务中。
- 审计只接受事务内 `PRAGMA journal_mode` 为 `delete`，并在初始哈希、事务查询和最终哈希边界检查 `-wal`、`-journal`、`-shm`；发现任何非空 sidecar 都直接报错。这样不会把 WAL 中已提交但尚未 checkpoint 的内容误绑定到主 SQLite 文件哈希。
- 查询前后各以 1 MiB 分块实际流式计算一次主 SQLite 文件的 SHA-256。两次哈希必须相同，且主文件 identity、size、mtime 在检查窗口内必须稳定。`database_sha256` 仅表示满足上述 `delete`/无非空 sidecar 前提时的主文件哈希，不表示 sidecar 内容的摘要。
- 88 人始终由 `background_contract.corpus_poet_profiles()` 动态取得；繁简候选名只用 `poet_reference_corpus.aliases_for_name()` 的受控 aliases。
- 审计流式扫描 `BIOG_MAIN.c_name_chn` 和 `ALTNAME_DATA.c_alt_name_chn`。随后以 `DYNASTIES` 边界与 birth/death/index/fl 年份进行唐（618–959）或宋（960–1279）过滤与确定性评分。
- 仅最高分唯一的候选进入 `unique`。最小人工绑定只有 `张志和=93417` 与 `张先=27114`；`常建` 固定保留 `[94489, 147391, 149973, 163667]` 歧义。

输出含 `source`、`database_sha256`、`unique`、`ambiguous`、`rule`、`accepted_names` 和 `selection_notes`。每个已选 `accepted_names` 都包含语料名与 CBDB 的原始 `c_name_chn`；受控 aliases 用于候选匹配，不膨胀稳定输出。

## 使用

默认行为只打印 JSON 并校验 87 个唯一绑定、仅常建歧义、87 个完整 `accepted_names`：

```powershell
python tools/cbdb_identity_audit.py
```

与现有快照做身份语义比对（比较 `unique`、`ambiguous` 和 `accepted_names`，不依赖额外审计说明字段）：

```powershell
python tools/cbdb_identity_audit.py --check-against data/candidates/cbdb_identity_audit_88.json
```

只有显式指定 `--output` 才会写文件；写入先落入同目录临时文件，`fsync` 后原子替换。写入前会通过路径 `resolve`，以及两端存在时的 `os.path.samefile`，拒绝把数据库本身、路径别名、符号链接或硬链接作为输出：

```powershell
python tools/cbdb_identity_audit.py --output tmp/cbdb_identity_audit_88.json
```

## 验证

```powershell
python tools/check_cbdb_identity_audit.py
```

检查覆盖临时 SQLite 的主名与别名、预期哈希不符、查询前后哈希/文件状态漂移、显式事务、同分歧义、两项 override、常建固定歧义及 `query_only` 拒写。数据库状态测试还包含真实 WAL 提交（主文件 hash/stat 保持不变）、无 sidecar 的 WAL 模式、真实 hot rollback journal、非空 SHM，以及查询期间出现 sidecar；这些输入均应报错。CLI 合同检查覆盖默认零落盘、原子 JSON 输出、同源/别名/硬链接拒绝且数据库原字节不变，以及语义负例返回 exit 2 且不产生输出。默认 CBDB 存在时必须运行只读集成比对，并要求 `unique=87`、歧义仅常建、`accepted_names=87` 与当前快照语义一致；通用环境缺少该缓存时会明确报告 integration skip。

该检查已注册到 `tools/check_all.py`，可单独运行：

```powershell
python tools/check_all.py --match "CBDB identity audit"
```
