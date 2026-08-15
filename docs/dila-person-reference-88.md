# DILA 人名權威資料參考採集（88 位詩人）

`tools/dila_person_reference_pipeline.py` 面向 DDBC Authority Web Services（DILA 佛學權威資料庫）
的人名查詢端點，為詩行萬里語料中的 88 位詩人補充「人名/朝代/生卒」參考識別記錄。本工具與行旅管線
刻意解耦：所有輸出都停留在 `data/candidates` 候選層，**出身地（birthPlace）僅作靜態參考，
永遠不會被寫入或路由為任何旅程事件**。

## 端點與服務說明

- 官方文件：<https://authority.dila.edu.tw/docs/services/person_query.php>
- 端點：`https://authority.dila.edu.tw/webwidget/getAuthorityData.php?type=person&id=<查詢>&jsoncallback=<callback>`
- 返回 JSONP（callback 為字面值，如 `cb1({...})`），可含多筆 `data1..dataN`；零結果為字面 `null`（HTTP 200）。
- 字段：`authorityID`、`name`、`dynasty`、`bornDateBegin/End`、`diedDateBegin/End`、`note`、
  `names`（別名）、`birthPlaceCode/Name`、`deathPlaceCode/Name`、`lang` 等。
- 缺日期可能為 `"unknown"`；缺朝代可能為 `"沒有給定朝代"`（均按「未知」處理）。
- `note` 可能含 HTML，採集器會先剝離標籤再截斷（≤300 字）。
- 當省略 `jsoncallback` 時，官方端點會直接輸出裸 JSON object 或字面 `null`；`parse_jsonp`
  同時接受裸 JSON 與 JSONP，但一旦存在 callback 包裹仍會驗證其語法。

### SSL 證書窄範圍回退（重要）

線上核對發現：HTTPS 端點可用，但 Python 默認嚴格證書校驗會因「Missing Subject Key Identifier」
拋出 `CERTIFICATE_VERIFY_FAILED`。本工具只在 **僅針對 `authority.dila.edu.tw` 這一個主機**、
且確實是證書校驗失敗時，對同一請求改用未驗證 context 重試一次（`open_dila_with_ssl_fallback`）。
**不全局關閉 SSL**，對任何其他主機不啟用任何回退，也非證書錯誤不會被吞掉。

未驗證的回退路徑使用 `_DilaHostRedirectHandler`：**只允許 authority.dila.edu.tw 同主機重定向**；
一旦伺服器把請求重定向到任何其他主機，直接拋出 `URLError` 中止——未驗證的 context 永不跟隨到非 DILA 主機。
正常（已驗證）首次請求仍使用系統默認證書校驗。

## 消歧規則（不取首條）

同名多人時**絕不「先到先得」**。對每個返回候選按三項得分後，唯一可信高分者才列 `matched`，
其餘同名候選一律保留以展示歧義（`ambiguous`）：

1. **姓名/別名**：精確名（exact_name）最高；其次簡繁對照別名、`names` 字段別名；僅「包含」詩人名
   （如「王維章」含「王維」）視為弱候選（substring，得分很低）。
2. **朝代**：與本地標籤（唐/宋）精確相等最高；相容族（如南唐/五代→唐）次之；朝代不符大幅扣分；
   缺失/「沒有給定朝代」為中性。
3. **生卒重疊（分開比較）**：**出生區間對本地生年、卒年區間對本地卒年分開比較**——用生卒並集重疊
   會對「生年、卒年都不合但並集有交集」的候選產生虛假加分。任何已知配對完全不重疊即為硬性矛盾
   （不可選）；任一方未知則該配對保持中性。本地通說生卒為近似值，比較時各放寬 ±3 年窗口
   （`LOCAL_YEAR_TOLERANCE=3`），避免「通說與權威範圍差一兩年」被誤判為矛盾。

已知線上樣例：李白 `A005220`（唐，生 701/702，卒 762）、杜甫 `A005221`；王建一次返回 5 行，
其中唐詩人為 `A017625`（唐、日期未知，位於響應中間而非首位），本規則以「精確名+朝代精確」
唯一選中 `A017625` 而非首條；李清照返回 `null`（零結果→`not_found`）。

## 網絡與緩存行為

- **嚴格同域順序、單線程**：`fetch_all` 依序逐詩人請求，任何兩次請求之間按 `--delay-min/--delay-max`
  均勻延遲，默認 5–8 秒；離線模式零網絡、零延遲。
- 本地語料多為簡體，而 DILA 名稱查詢以繁體詞形命中；工具先生成確定性的繁體別名再查詢，返回後仍以
  簡繁別名、朝代和生卒範圍共同消歧，不把第一條結果當作唯一人物。
- 有限重試（`--retries`，默認 2）：timeout / `socket.timeout` / 429 / **全部 5xx（500–599）** 才重試，
  優先採用 `Retry-After`，否則指數退避（上限 15s）；非可重試 4xx 立即停止。
- 緩存：`.cache/background_sources/dila_person/`，內容定址 + 元數據校驗和；`--offline` 僅用
  通過 checksum 校驗的緩存。
- 失敗顯式持久化：`fetch_failed` / `parse_failed` 連同 http_status、retry_count、error 寫入覆蓋報告；
  **失敗不會抹除已存在的舊匹配記錄**，也不縮小 88 人覆蓋。
- 合併語義：**本次成功取得的新鮮響應**（`fetched` 或離線 `cache_hit`）且成功解析的詩人
  （含解析為 not_found、即候選為空者）會以新結果替換其舊行，從而清掉陳舊候選；
  `fetch_failed`/`parse_failed` 的詩人保留舊行；**`fetch_failed_cache_used`（網絡失敗＋陳舊緩存）
  即使緩存體可解析也不會替換**——舊行與先前狀態保留，attempt 仍記錄本次失敗；未選詩人一律保留舊行。
- `--resume` 跳過已有 `matched/ambiguous` 持久化記錄的詩人；`--poets` 子集運行不會擦除無關舊記錄，
  且覆蓋報告會**保留未選詩人上一次的狀態與 attempt**（不會被降為 `not_fetched`）。

## 允許輸出的文件（本工具只寫這些）

- `data/candidates/poet_dila_person_matches.jsonl`（候選匹配行，含
  `source_url`、`authorityID`、`canonical_name`、`aliases`、`dynasty`、`born_range`/`died_range`、
  `birth_place`、`note`、`accessed_at`、`license_note`、`match_status`，以及 `birthplace_reference_only=true`）
- `data/candidates/poet_dila_person_coverage.json`
- `.cache/background_sources/dila_person/**`

匹配行不含任何路線/事件字段（無 `event_type`、`year_start`、`lon/lat`、`historical_place` 等）。

## 來源與許可證聲明

- 來源：DDBC Authority 開放內容（Open Content），見 <https://authority.dila.edu.tw/docs/open_content/>。
- 官方授權：**CC BY-SA 2.5 台灣（CC BY-SA 2.5 TW）**，官方連結
  <https://creativecommons.org/licenses/by-sa/2.5/tw/>。
- 注意：person_query 說明頁本身未再逐條重申每筆記錄之授權條款，使用前請以 Open Content 頁面為準。
- 本工具僅作人名/朝代/生卒參考識別，**不是事實、行年或路線證據**。

## 解釋性警告（Interpretation Warning）

- DILA 為佛學與歷史人名權威庫，其朝代粒度與本地標籤可能不同（如南唐/五代），且部分詩人生卒不詳；
  缺日期時消歧只依賴姓名與朝代，請勿把本輸出當作精確行年。
- 同名候選的 `ambiguous` 行是「展示歧義」用的完整證據，不是錯誤；任何後續使用都必須手動核對 `authorityID`。
- 出身地是靜態參考，**永遠不得**作為作詩地點或事件路由依據（`birthplace_reference_only=true`）。

## 復現與驗證

```powershell
python tools/check_dila_person_reference_pipeline.py
python tools/dila_person_reference_pipeline.py check
```

72 項離線 fixture 測試全綠（`python -W error::ResourceWarning tools/check_dila_person_reference_pipeline.py`，
零 ResourceWarning 噪音），覆蓋：JSONP/裸 JSON 解析（callback 包裹、多筆 dataN、行元數據、裸 object、字面 null）、
歧義（同名並列、王建五行非首條、李清照零結果）、別名/朝代/生卒分開評分（含並集虛假加分反例）、
not-found、失敗與重試（429 Retry-After、5xx 全範圍含 507、TimeoutError、socket.timeout、非重試 4xx）、
SSL 窄範圍回退（含**跨主機重定向拒絕**與回退開瓶器接線測試）、緩存校驗和、
順序/延遲、resume、子集保留與先前狀態保留、成功 not_found 清陳舊候選、
**fetch_failed_cache_used 保留舊行/狀態但記錄 attempt**、原子/冪等（快照式）/
generated_at 語義保留、88 人 roster、無路線事件字段、CC BY-SA 2.5 TW 許可證措辭、HTTPError 顯式關閉。

## 88 人線上運行

本轮已按同域顺序、单线程完成 88 人在线采集：

- `matched=64`
- `ambiguous=3`
- `not_found=21`
- 持久化候选记录 `77` 条（歧义人物保留多条候选）
- 网络瞬时失败 `0`

复跑命令：

```powershell
python tools/dila_person_reference_pipeline.py collect --scope all --resume --delay-min 3 --delay-max 5
```
