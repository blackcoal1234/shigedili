# CBDB 坐标回填（严格直接联接）

`tools/cbdb_coordinate_backfill.py` 是一个离线、只读、确定性的坐标回填工具：仅对 `source=cbdb` 且当前无 lon/lat 的六位目标诗人候选记录，按 `candidate.cbdb_addr_id = ADDR_CODES.c_addr_id` 直接联接，不接受出生地、索引地、上级行政区、现代代表城市或任何推断。

## 输入与只读保证

- 数据库只读：`.cache/background_sources/cbdb/latest.sqlite3`，以 SQLite `mode=ro` + `PRAGMA query_only` 打开，全部 `SELECT` 位于一个显式只读事务内，不创建/改变 WAL 或 journal。
- 查询前后各以 1 MiB 分块实际流式计算一次主数据库 SHA-256；两次哈希必须一致，且主文件 identity、size、mtime 在检查窗口内保持稳定。`-wal`/`-journal`/`-shm` 非空 sidecar 在初始哈希、事务查询、最终哈希边界均被拒绝。
- 目标诗人：司空曙、卢纶、李益、司马光、欧阳炯、钱惟演。目标记录仅 `source=cbdb` 且当前无 lon/lat。
- 输出不允许通过路径别名、符号链接或硬链接指向任何输入文件。

## 表结构与联接

只使用 `ADDR_CODES` 一张表（列 `c_addr_id`、`c_name_chn`、`c_firstyear`、`c_lastyear`、`x_coord`、`y_coord`、`CHGIS_PT_ID`）。联接键：`candidate.cbdb_addr_id = ADDR_CODES.c_addr_id`。

接受条件（全部满足才补充）：

- `ADDR_CODES` 行存在；
- `c_name_chn` 与 `historical_place` 规范化空白后相同；
- `x_coord`/`y_coord` 均为有限数，且经度 [-180,180]、纬度 [-90,90]；拒绝 `(0,0)` 哨兵；
- 事件 `year_start`/`year_end` 与 `ADDR_CODES` `c_firstyear`/`c_lastyear`（若有）相交。

## 等级口径

- `coordinate_grade = A`：坐标有效且 `chgis_pt_id` 非空。
- `coordinate_grade = B`：坐标有效但 `chgis_pt_id` 为空。
- `fact_grade` 保留候选记录的 `source_grade`。
- `stable_link_key` 由不可变关联字段（source、poet、cbdb_person_id、cbdb_addr_id、event_type、year_start、year_end、historical_place）确定性推导。

## 总体统计

- 目标记录：30
- 成功补充：19
- 未补记录：11
- 数据库 SHA-256：`ec0be08186722c53f77b47f4513239afd6a505f8157994cc72b9fbd49c6fc21a`

### 分诗人成功统计

| 诗人 | 成功 | 未补 |
| --- | --- | --- |
| 司空曙 | 1 | 1 |
| 卢纶 | 3 | 0 |
| 李益 | 4 | 2 |
| 司马光 | 9 | 5 |
| 欧阳炯 | 1 | 0 |
| 钱惟演 | 1 | 3 |

### 等级分布：A=17，B=2

## 成功补充清单

| candidate_id | 诗人 | event_year | place | lon | lat | addr_id | grade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8ef0f22b2983b8645142d103524a19200c3fce7aa2fae427c88c5dfb1a0eb83f | 卢纶 | 771 | 閿鄉 | 110.441903 | 34.58722 | 14733 | A |
| 4faa21d235d34c08db372071b3b784821a9970b2fdc7d1e35204b439c8d651de | 卢纶 | 779 | 陝州 | 111.36267853 | 34.656059265 | 14719 | A |
| 2e76a38121ded4b82537519ca9b4e366da88ea2fc29629992cf403c070bdf10d | 卢纶 | 780 | 昭應 | 109.305123 | 34.355559 | 14497 | A |
| 92a75f90e4b2aaa0037ce1227044abe497b91151737c7ee92ad88cb6704ce470 | 司空曙 | 779 | 長林 | 112.024668 | 31.085796 | 15450 | A |
| 3b71cb40c52b96ae31bee3ef7de538675bbb15e3d49a9ed5eebc46a02664e93c | 司马光 | 1039 | 蘇州 | 120.61862183 | 31.312709808 | 12688 | A |
| f27f16a0d752f458bf5c56f386dfc3c7c15ef3d3db4b414a18625218ce2a89d1 | 司马光 | 1045 | 韋城 | 114.77003 | 35.418397 | 100628 | A |
| d6d67b664788c38e874eeca707adddac4abe66e12d863db9da2fa63d0a546f82 | 司马光 | 1054 | 鄆州 | 116.28256226 | 35.956073761 | 101057 | A |
| 18c5a35ea01f2c7b140cdb894c5c64995c4bb40f4618ba3821eade2f9e74f3b2 | 司马光 | 1054-1057 | 并州 | 112.74468 | 37.67847 | 12215 | B |
| d8b8f9443d0e39240f28d20a0983ccfd3c8eaa929aca7cc15cf1a19e041eaea8 | 司马光 | 1058 | 開封府 | 114.34333 | 34.785477 | 11027 | A |
| 6bdcdd6e1b74b743ce0d1eb191be815767e32ee084e6632174f790ab248dfbbd | 司马光 | 1070 | 京兆府 | 108.94420624 | 34.266605377 | 11902 | A |
| 3f8d06dea3e7de66236a0a3afbc771d94566a73426634761875625753a67549b | 司马光 | 1071 | 洛陽 | 112.38263 | 34.665276 | 100409 | A |
| 8963aa8b45bd0ec5a7445881fd1418a59d4dca3ba4995cdf7ae0f94e47f7faa5 | 司马光 | 1071-1073 | 河南府 | 112.38262939 | 34.665275574 | 11372 | A |
| 6a7a9ab958b4a8430e5d06ebcf050097eec3f019e7eb2abb861420716b8b6b55 | 司马光 | 1073-1085 | 河南府 | 112.38262939 | 34.665275574 | 11372 | A |
| 720a53f40869f5dbcca845f6109059c2a18aee96c2496a77487f4aded1318c06 | 李益 | 797 | 幽州 | 116.326 | 39.8768 | 15370 | B |
| 36e37d0ecae2791c9f27ab5e48d7c33d7f12096ea232ba710d747217e9475ea0 | 李益 | 810 | 河南府 | 112.38263 | 34.665276 | 14691 | A |
| 48099b516aa3d390ebb9f913a0141946b4f121df40cc6459ae612a8e6829c5d5 | 李益 | 829 | 河南 | 112.38263 | 34.665276 | 14692 | A |
| 5b742463e0748d64965247ba05636bf859a41b8fd483128165c09d483424f1d6 | 李益 | 829 | 偃師 | 112.804997 | 34.720623 | 14694 | A |
| 061aa12753e6d8e23692ac46af0d167721bcf7273529ef19c4b5dd84c1fa5c40 | 欧阳炯 | 925 | 秦州 | 105.71695709 | 34.585472107 | 16690 | A |
| 94a9bd3a8a2ec5dd67e5622002b9901e7930ae9d7619f2d54ff947942f15597a | 钱惟演 | 1023-1024 | 亳州 | 115.77090454 | 33.879291534 | 12446 | A |

## 未补记录明细

| candidate_id | 诗人 | 年份 | place | addr_id | reason |
| --- | --- | --- | --- | --- | --- |
| 8f6fb139ddf657e9fcb27ced759871c8ed7c40e8980f2bef58df04271b6eac4a | 司空曙 | 785 | 劍南西川軍節度 | 400288 | DB NULL（坐标缺失） |
| 96d971901c515a8f98548d752867dd6e5551ce27a428eb6fa520ab579ffa8d0d | 司马光 | 1044 | 武成軍節度 | 100369 | DB NULL（坐标缺失） |
| 80c3ff3428cae3f8b8c97375902fb7682c51356a086df0ecc72e5c8e8264ade9 | 司马光 | 1044-1045 | 武成軍節度 | 100369 | DB NULL（坐标缺失） |
| 923bb7f7f03300581c4fe3546102cc41e8ee1e1afda21002cbcfecc6f5dbb206 | 司马光 | 1070 | 永興軍節度 | 101161 | DB NULL（坐标缺失） |
| dc991f7e3cf0b6c297752a94dbc5c042f7e675dbdfd54810e239e1f6b283605f | 司马光 | 1086 | 宋朝 | 10989 | DB NULL（坐标缺失） |
| b465bae11542f48ca35af328b98af18f8ae472b3d825dfad848b6ba9d719de05 | 司马光 | 1086 | 溫國 | 25022 | **SENTINEL (0,0)（哨兵，拒绝 (0,0)）** |
| 6577b706fb7b402ece6d240e868aa9afdfa8ed7f01c0c1e4438b5999efcddc4e | 李益 | 780-781 | 朔方道 | 400317 | DB NULL（坐标缺失） |
| 7bcfdbfaaaef11aa94aa0a63a3d7c9e2249564f51bca21c09718fa26299ab4dc | 李益 | 788-796 | 邠寧軍節度 | 400287 | DB NULL（坐标缺失） |
| 10fbc1eeab6206e3647ca69832ae6e0d751feb4ee14ace83670752761f975834 | 钱惟演 | 1020-1021 | 宋朝 | 10989 | DB NULL（坐标缺失） |
| f71275fcbcd72363beebb2eed5aeeabc572ee77d989b7e37d2cbffe25b186b87 | 钱惟演 | 1022 | 宋朝 | 10989 | DB NULL（坐标缺失） |
| a52c5f16eb9633f5e6c566057d3c8dd59e4065455bd30ecd7d3d0b4b77642e0e | 钱惟演 | 1023 | 保大軍節度 | 30053 | DB NULL（坐标缺失） |

## 复现与验证

```powershell
python tools/cbdb_coordinate_backfill.py
python tools/check_cbdb_coordinate_backfill.py
```
