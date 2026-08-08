# 台股網路熱度搜尋器

追蹤一籃子台股標的在網路上的**討論熱度**與**搜尋曝光度**,每日自動更新,
以靜態網頁呈現可排序的熱度排行榜。

## 熱度指標

| 指標 | 來源 | 說明 |
|---|---|---|
| PTT 文章數 | PTT Stock 板 | 視窗內「標題」含股票名稱或代號的文章數 |
| PTT 留言數 | PTT Stock 板 | 上述文章的推/噓/箭頭留言總數 |
| 新聞則數 | Google News RSS(zh-TW) | 視窗內的新聞報導數(單次上限 100,超過標示 `+`) |
| 量能變化 | 證交所 / 櫃買中心 | 視窗內日均成交金額相對前一期的變化率 |

綜合熱度分數 = 各指標正規化(0~100)後加權:
PTT 文章 25% + PTT 留言 25% + 新聞 30% + 量能變化 20%。
某來源整體無資料時,權重自動重新分配。

統計視窗:**近 1 天 / 7 天 / 30 天**,網頁上可切換。

> PTT 官方站(ptt.cc)會封鎖雲端機房 IP,因此 PTT 資料改經
> [pttweb.cc](https://www.pttweb.cc) 鏡像站的公開 API 取得。

## 使用方式

### 產生報表

需要 Python 3.10+,純標準庫、無需安裝任何套件:

```bash
python3 src/main.py              # 完整執行(約 3~5 分鐘)
python3 src/main.py --limit 3    # 只跑前 3 檔(快速測試)
python3 src/main.py --skip-volume  # 略過成交量
```

產出:

- `data/heat.json` — 完整報表資料(各視窗指標、分數、排名、熱門文章/新聞連結)
- `docs/data.js` — 供網頁載入的同份資料

### 檢視排行榜

直接用瀏覽器開啟 `docs/index.html` 即可(支援 `file://`,不需架伺服器)。

功能:1/7/30 天視窗切換、任一欄位排序、名稱/代號篩選、
點擊列展開該股的 PTT 熱門文章與最新新聞連結。

也可以在 GitHub repo 設定中開啟 **Pages**(Source 選 `main` 分支的 `/docs` 目錄),
就能取得公開網址。

### 每日自動更新

`.github/workflows/update.yml` 已設定每天台北時間 22:30 自動抓取資料並提交更新,
也可以在 GitHub Actions 頁面手動觸發(workflow_dispatch)。

## 修改股票清單

編輯 `config/stocks.json`,每檔股票欄位:

```jsonc
{
  "name": "台積電",        // 顯示名稱
  "code": "2330",          // 代號
  "market": "twse",        // twse = 上市,tpex = 上櫃(設錯會自動改試另一邊)
  "ptt_queries": ["..."],  // 選填:PTT 標題搜尋關鍵字,預設 [name, code]
  "news_query": "..."      // 選填:Google News 關鍵字,預設 name
}
```

名稱有歧義的股票建議自訂關鍵字,例如「世界」(5347)改用「世界先進」、
「創意」(3443)的新聞搜尋改用「創意電子」。

## 專案結構

```
config/stocks.json      股票清單設定檔
src/
  main.py               主程式(抓取 → 計分 → 輸出)
  fetch_ptt.py          PTT Stock 板(pttweb.cc Twirp API)
  fetch_news.py         Google News RSS
  fetch_volume.py       證交所 / 櫃買中心成交量
  scoring.py            指標統計、正規化、加權計分
  common.py             HTTP 工具與設定載入
docs/
  index.html            排行榜網頁(靜態,免伺服器)
  data.js               產出的資料(自動更新)
data/heat.json          產出的完整報表
.github/workflows/update.yml  每日自動更新排程
```

## 已知限制

- PTT 只比對文章**標題**,內文提及不計;經 pttweb.cc 鏡像,極新文章可能有數小時延遲。
- Google News RSS 單次查詢最多 100 則,超熱門股的 30 天新聞數會低估(以 `+` 標示)。
- 「創意」「世界」等通用詞名稱即使自訂關鍵字仍可能有少量誤判。
- 本工具僅供參考,不構成投資建議。
